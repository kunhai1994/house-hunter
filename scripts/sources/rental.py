"""租金采集 — 链家 / 贝壳 / 自如 网页抓取。

通过 WebFetch 抽取（节流 + 缓存），不直接爬虫，避免封禁。
失败时按 链家 → 贝壳 → 自如 → 安居客 的顺序回退。

注意：
  - 这里实现的是骨架 + URL 拼装 + 公开页面 HTML 解析逻辑。
  - 返回结构稳定：top_communities() 返回 [{"id","name","price_per_sqm","district","url"}]
  - 实际 HTML 结构可能随网站变化，需要时做小幅调整。
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import http_get, cached, RateLimiter, warn  # type: ignore


_rate = RateLimiter(min_interval_s=2.5)  # 网页抓取严格节流

# 城市拼音映射 — **增强白名单**（链家/贝壳 URL 子域）
# 命中此表 → 走链家精细数据（户型/挂牌量/挂牌价等）
# 未命中 → 自动降级到「百度地图 POI 搜小区」兜底（候选数偏少但任意城市可用）
CITY_PINYIN = {
    # 直辖市 / 一线
    "深圳市": "sz", "深圳": "sz", "shenzhen": "sz",
    "上海市": "sh", "上海": "sh", "shanghai": "sh",
    "北京市": "bj", "北京": "bj", "beijing": "bj",
    "广州市": "gz", "广州": "gz", "guangzhou": "gz",
    "天津市": "tj", "天津": "tj", "tianjin": "tj",
    "重庆市": "cq", "重庆": "cq", "chongqing": "cq",

    # 新一线
    "杭州市": "hz", "杭州": "hz", "hangzhou": "hz",
    "成都市": "cd", "成都": "cd", "chengdu": "cd",
    "武汉市": "wh", "武汉": "wh", "wuhan": "wh",
    "南京市": "nj", "南京": "nj", "nanjing": "nj",
    "苏州市": "su", "苏州": "su", "suzhou": "su",
    "西安市": "xa", "西安": "xa", "xian": "xa",
    "长沙市": "cs", "长沙": "cs", "changsha": "cs",
    "郑州市": "zz", "郑州": "zz", "zhengzhou": "zz",
    "青岛市": "qd", "青岛": "qd", "qingdao": "qd",
    "沈阳市": "sy", "沈阳": "sy", "shenyang": "sy",
    "宁波市": "nb", "宁波": "nb", "ningbo": "nb",
    "东莞市": "dg", "东莞": "dg", "dongguan": "dg",
    "无锡市": "wx", "无锡": "wx", "wuxi": "wx",
    "合肥市": "hf", "合肥": "hf", "hefei": "hf",
    "佛山市": "fs", "佛山": "fs", "foshan": "fs",

    # 二线
    "福州市": "fz", "福州": "fz", "fuzhou": "fz",
    "厦门市": "xm", "厦门": "xm", "xiamen": "xm",
    "哈尔滨市": "hrb", "哈尔滨": "hrb",
    "长春市": "cc", "长春": "cc", "changchun": "cc",
    "大连市": "dl", "大连": "dl", "dalian": "dl",
    "济南市": "jn", "济南": "jn", "jinan": "jn",
    "昆明市": "km", "昆明": "km", "kunming": "km",
    "贵阳市": "gy", "贵阳": "gy",
    "南宁市": "nn", "南宁": "nn",
    "南昌市": "nc", "南昌": "nc",
    "太原市": "ty", "太原": "ty",
    "石家庄市": "sjz", "石家庄": "sjz",
    "海口市": "hk", "海口": "hk",
    "三亚市": "sanya", "三亚": "sanya",

    # 珠三角 / 长三角 强地级市
    "珠海市": "zh", "珠海": "zh",
    "中山市": "zs", "中山": "zs", "zhongshan": "zs",
    "惠州市": "hui", "惠州": "hui",
    "江门市": "jm", "江门": "jm",
    "汕头市": "shantou", "汕头": "shantou",
    "湛江市": "zhanjiang", "湛江": "zhanjiang",
    "常州市": "changzhou", "常州": "changzhou",
    "南通市": "nt", "南通": "nt",
    "徐州市": "xz", "徐州": "xz",
    "扬州市": "yz", "扬州": "yz",
    "温州市": "wz", "温州": "wz",
    "绍兴市": "sx", "绍兴": "sx",
    "嘉兴市": "jx", "嘉兴": "jx",
    "金华市": "jh", "金华": "jh",
    "泉州市": "qz", "泉州": "qz",
    "烟台市": "yt", "烟台": "yt",
    "唐山市": "ts", "唐山": "ts",
    "保定市": "bd", "保定": "bd",
    "廊坊市": "lf", "廊坊": "lf",
}


def is_lianjia_supported(city: str) -> bool:
    """城市是否在链家增强白名单内。"""
    return city in CITY_PINYIN

# 区拼音映射（节选；缺失时用 None，对应链家会落回到城市级）
DISTRICT_PINYIN = {
    ("深圳市", "南山区"): "nanshan",
    ("深圳市", "福田区"): "futian",
    ("深圳市", "罗湖区"): "luohu",
    ("深圳市", "宝安区"): "baoan",
    ("深圳市", "龙岗区"): "longgang",
    ("深圳市", "龙华区"): "longhua",
    ("深圳市", "坪山区"): "pingshan",
    ("深圳市", "光明区"): "guangmingxinqu",
    ("深圳市", "盐田区"): "yantian",
}


def city_pinyin(city: str) -> str | None:
    return CITY_PINYIN.get(city)


def district_pinyin(city: str, district: str) -> str | None:
    return DISTRICT_PINYIN.get((city, district))


# ---------------------------------------------------------------------------
# 网页抓取（带 UA + 节流 + 缓存）
# ---------------------------------------------------------------------------
COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}


def _is_login_page(html: str) -> bool:
    """检测链家是否返回了反爬页面（登录页 / CAPTCHA / 风控拦截页）。"""
    if not html or len(html) < 2000:
        return True  # 正常租房列表页都 > 50KB
    # 标题特征
    import re as _re
    title_match = _re.search(r'<title[^>]*>([^<]+)</title>', html)
    if title_match:
        t = title_match.group(1).strip()
        # CAPTCHA / 人机验证 页
        if _re.search(r'captcha|verify|验证码|人机验证|安全验证|滑块验证|拼图验证', t, _re.I):
            return True
        # 登录页
        if t in ("登录", "登 录", "请登录", "账号登录", "登录注册"):
            return True
    # 正文特征
    if "ke-passport" in html and "<title>登录</title>" in html:
        return True
    return False


@cached("rental_html", ttl_seconds=86400)
def fetch_html(url: str) -> str | None:
    """Fetch lianjia/ke HTML，三层 fallback：
      1. urllib 直爬（免费，最快；但反爬严重时常失败）
      2. Housing Bridge（用户已登录浏览器，真 cookie+TLS；绕反爬）
      3. 都失败返 None（让上层走百度 POI 兜底）
    """
    _rate.wait(url.split("/")[2] if "://" in url else "default")
    html = http_get(url, timeout=15, headers=COMMON_HEADERS)
    if html and not _is_login_page(html):
        return html

    # Bridge fallback
    try:
        # 延迟 import 避免循环依赖；housing_bridge 不在时安全跳过
        from sources import housing_bridge  # type: ignore
        if housing_bridge.is_bridge_running():
            html2 = housing_bridge.fetch_html(url)
            if html2:
                return html2
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# 链家：热门小区 + 租金
# ---------------------------------------------------------------------------
def lianjia_zufang_url(city: str, district: str | None = None,
                       host: str = "ke.com") -> str | None:
    """租房列表页 URL。默认 ke.com (贝壳第一)，可通过 host 切到 lianjia.com。"""
    cp = city_pinyin(city)
    if not cp:
        return None
    if district:
        dp = district_pinyin(city, district)
        if dp:
            return f"https://{cp}.{host}/zufang/{dp}/"
    return f"https://{cp}.{host}/zufang/"


def lianjia_xiaoqu_url(city: str, district: str | None = None,
                       host: str = "ke.com") -> str | None:
    """小区列表页 URL。默认 ke.com (贝壳第一)，可通过 host 切到 lianjia.com。"""
    cp = city_pinyin(city)
    if not cp:
        return None
    if district:
        dp = district_pinyin(city, district)
        if dp:
            return f"https://{cp}.{host}/xiaoqu/{dp}/"
    return f"https://{cp}.{host}/xiaoqu/"


@cached("rental_top", ttl_seconds=86400)
def top_communities(city: str, district: str | None = None,
                    limit: int = 10) -> list[dict]:
    """获取热门小区清单（按租房挂牌量排序）。贝壳第一，链家 fallback。"""
    # ke 第一，lianjia 备用
    html = None
    for host in ("ke.com", "lianjia.com"):
        url = lianjia_zufang_url(city, district, host=host)
        if not url:
            continue
        html = fetch_html(url)
        if html:
            break
    if not html:
        return []
    return _parse_lianjia_zufang_list(html, city)[:limit]


def _parse_lianjia_zufang_list(html: str, city: str) -> list[dict]:
    """从链家租房列表解析 → 聚合到小区。

    简化策略：解析所有 listing 条目，按小区名分组，统计挂牌数 + 取均价。
    Lianjia 列表页常见结构：
      <a class="content__list--item--aside" href="/zufang/SH123.html" title="..."></a>
      <p class="content__list--item--des"><a href="/zufang/baoan/">宝安</a>-<a>新安</a>-<a href=".../xiaoqu/2123/">某小区</a></p>
      <span class="content__list--item-price"><em>3500</em>元/月</span>
    """
    items = re.findall(
        r'<div class="content__list--item--main">(.*?)</div>\s*</div>',
        html, re.DOTALL,
    )
    aggreg: dict[str, dict] = {}
    for raw in items:
        name_match = re.search(
            r'<a[^>]+href="(/xiaoqu/\d+/?)"[^>]*>([^<]+)</a>',
            raw,
        )
        price_match = re.search(r'<span class="content__list--item-price"><em>(\d+)</em>', raw)
        district_match = re.search(
            r'<a[^>]+href="/zufang/[a-z]+/"[^>]*>([^<]+)</a>',
            raw,
        )
        if not name_match or not price_match:
            continue
        cid = name_match.group(1).strip("/").split("/")[-1]
        cname = name_match.group(2).strip()
        price = int(price_match.group(1))
        agg = aggreg.setdefault(cid, {
            "id": cid, "name": cname,
            "city": city,
            "district": district_match.group(1).strip() if district_match else None,
            "listings": 0, "rent_total": 0,
        })
        agg["listings"] += 1
        agg["rent_total"] += price
    out = []
    for c in aggreg.values():
        c["rent_avg"] = round(c["rent_total"] / c["listings"]) if c["listings"] else None
        c.pop("rent_total", None)
        c["url"] = f"https://{city_pinyin(city) or 'sh'}.ke.com/xiaoqu/{c['id']}/"
        out.append(c)
    out.sort(key=lambda x: x.get("listings", 0), reverse=True)
    return out


@cached("rental_summary", ttl_seconds=86400)
def community_rental_summary(community_id: str, city: str) -> dict | None:
    """单个小区的租金摘要：一房/两房/三房/合租 各档位均价 + 挂牌量。

    URL 顺序（贝壳第一，链家 fallback）：
      https://{city}.ke.com/zufang/c{community_id}/        ← 贝壳，首选
      https://{city}.lianjia.com/zufang/c{community_id}/   ← 链家，fallback
    """
    cp = city_pinyin(city)
    if not cp:
        return None

    # 贝壳第一
    for host in ("ke.com", "lianjia.com"):
        url = f"https://{cp}.{host}/zufang/c{community_id}/"
        html = fetch_html(url)
        if html:
            break
    if not html:
        return None

    by_room: dict[int, dict] = {1: {"prices": [], "count": 0},
                                2: {"prices": [], "count": 0},
                                3: {"prices": [], "count": 0}}
    shared = {"prices": [], "count": 0}

    items = re.findall(
        r'<div class="content__list--item--main">(.*?)</div>\s*</div>',
        html, re.DOTALL,
    )
    for raw in items:
        # 例: 整租·xx · 65㎡ · 朝南 · 2室1厅
        is_shared = "合租" in raw
        room_match = re.search(r'(\d+)室', raw)
        price_match = re.search(r'<em>(\d+)</em>', raw)
        if not price_match:
            continue
        price = int(price_match.group(1))
        if is_shared:
            shared["prices"].append(price)
            shared["count"] += 1
            continue
        if not room_match:
            continue
        rooms = int(room_match.group(1))
        if rooms in by_room:
            by_room[rooms]["prices"].append(price)
            by_room[rooms]["count"] += 1

    def _summarize(d: dict) -> dict:
        ps = d["prices"]
        if not ps:
            return {"avg": None, "min": None, "max": None, "count": 0}
        return {
            "avg": round(sum(ps) / len(ps)),
            "min": min(ps),
            "max": max(ps),
            "count": len(ps),
        }

    return {
        "community_id": community_id,
        "url": url,
        "one_bedroom": _summarize(by_room[1]),
        "two_bedroom": _summarize(by_room[2]),
        "three_bedroom": _summarize(by_room[3]),
        "shared_room": _summarize(shared),
        "total_listings": sum(d["count"] for d in [*by_room.values(), shared]),
    }


# ---------------------------------------------------------------------------
# 链家：小区基础信息（建成年份、楼栋等）
# ---------------------------------------------------------------------------
@cached("rental_basic", ttl_seconds=86400 * 7)
def community_basic_info(community_id: str, city: str) -> dict | None:
    """从贝壳/链家 xiaoqu 详情页提取建成年份、楼栋数、户数、物业等。

    URL 顺序（贝壳第一，链家 fallback）：
      https://{city}.ke.com/xiaoqu/{community_id}/        ← 贝壳，首选
      https://{city}.lianjia.com/xiaoqu/{community_id}/   ← 链家，fallback
    """
    cp = city_pinyin(city)
    if not cp:
        return None

    url = None
    html = None
    for host in ("ke.com", "lianjia.com"):
        url = f"https://{cp}.{host}/xiaoqu/{community_id}/"
        html = fetch_html(url)
        if html:
            break
    if not html:
        return None

    info: dict[str, Any] = {"community_id": community_id, "url": url}

    name_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
    if name_match:
        info["name"] = name_match.group(1).strip()

    # 从 xiaoquInfo 提取
    pairs = re.findall(
        r'<span class="xiaoquInfoLabel">([^<]+)</span>\s*<span class="xiaoquInfoContent[^"]*"[^>]*>([^<]+)</span>',
        html,
    )
    for label, value in pairs:
        v = value.strip().replace("&nbsp;", "")
        if "建成年代" in label:
            year_match = re.search(r'(\d{4})', v)
            if year_match:
                info["built_year"] = int(year_match.group(1))
        elif "楼栋总数" in label:
            n = re.search(r'(\d+)', v)
            if n:
                info["building_count"] = int(n.group(1))
        elif "房屋总数" in label:
            n = re.search(r'(\d+)', v)
            if n:
                info["unit_count"] = int(n.group(1))
        elif "物业公司" in label:
            info["property_company"] = v

    # 地址（detailDesc 是链家详情页的小区地址栏）
    addr_match = re.search(
        r'<div class="detailDesc"[^>]*>([^<]+)</div>',
        html,
    )
    if addr_match:
        info["address"] = addr_match.group(1).strip().replace("&nbsp;", "")

    # 经纬度（用于地图查询的回退）
    loc_match = re.search(r"resblockPosition[\"']?\s*[:=]\s*[\"']([^,\"']+),([^\"']+)[\"']", html)
    if loc_match:
        try:
            info["lng"] = float(loc_match.group(1))
            info["lat"] = float(loc_match.group(2))
        except ValueError:
            pass

    return info if len(info) > 2 else None


# ---------------------------------------------------------------------------
# 自如（合租主卧均价回退）— 暂只做 URL 拼装与简单解析
# ---------------------------------------------------------------------------
def ziroom_search_url(city: str, keyword: str) -> str:
    cp = {"深圳市": "shenzhen", "上海市": "shanghai", "北京市": "beijing",
          "广州市": "guangzhou"}.get(city, "shenzhen")
    return f"https://{cp}.ziroom.com/z/?keyword={urllib.parse.quote(keyword)}"


def health() -> bool:
    """简单 ping：能不能访问链家深圳首页。"""
    return fetch_html("https://sz.lianjia.com/") is not None
