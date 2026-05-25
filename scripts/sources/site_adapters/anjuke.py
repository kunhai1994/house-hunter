"""Anjuke (安居客 anjuke.com) adapter — 58 系综合二手房/租房平台。

特点：覆盖城市最广，中介房源池大；HTML 模板跟链家完全不同。
反爬较强（与 58 共一套）。

URL 模式（2024-2026 常见）：
  - 城市子域：{cp}.anjuke.com（深圳 = shenzhen）
  - 全城小区：https://{cp}.anjuke.com/community/
  - 按区：    https://{cp}.anjuke.com/community/{district_pinyin}/
  - 详情页：  https://{cp}.anjuke.com/community/view/{community_id}
  - 租房列表：https://{cp}.anjuke.com/rental/{community_pinyin_or_id}/
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sources.site_adapters import (  # type: ignore
    CommunityInfo, PriceInfo, register,
)


# 安居客用全拼音子域，跟链家短拼音不同
_CITY_PINYIN = {
    "深圳市": "shenzhen", "深圳": "shenzhen",
    "上海市": "shanghai", "上海": "shanghai",
    "北京市": "beijing",  "北京": "beijing",
    "广州市": "guangzhou","广州": "guangzhou",
    "杭州市": "hangzhou", "杭州": "hangzhou",
    "成都市": "chengdu",  "成都": "chengdu",
    "武汉市": "wuhan",    "武汉": "wuhan",
    "南京市": "nanjing",  "南京": "nanjing",
    "天津市": "tianjin",  "天津": "tianjin",
    "重庆市": "chongqing","重庆": "chongqing",
    "苏州市": "suzhou",   "苏州": "suzhou",
    "西安市": "xian",     "西安": "xian",
    "长沙市": "changsha", "长沙": "changsha",
    "郑州市": "zhengzhou","郑州": "zhengzhou",
}

# 区拼音（节选深圳）
_DISTRICT_PINYIN = {
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


class AnjukeAdapter:
    SITE_NAME = "anjuke"
    HOST = "anjuke.com"
    SUPPORTED_CITIES = set(_CITY_PINYIN.keys())

    def _cp(self, city: str) -> str | None:
        return _CITY_PINYIN.get(city)

    def _dp(self, city: str, district: str | None) -> str | None:
        if not district:
            return None
        return _DISTRICT_PINYIN.get((city, district))

    # ─── URL 构造 ───
    def search_community_url(self, city: str, district: str | None) -> str | None:
        cp = self._cp(city)
        if not cp:
            return None
        dp = self._dp(city, district)
        if dp:
            return f"https://{cp}.{self.HOST}/community/{dp}/"
        return f"https://{cp}.{self.HOST}/community/"

    def community_detail_url(self, community_id: str, city: str) -> str | None:
        cp = self._cp(city)
        if not cp or not community_id:
            return None
        return f"https://{cp}.{self.HOST}/community/view/{community_id}"

    def listings_url(self, community_id: str, city: str) -> str | None:
        cp = self._cp(city)
        if not cp or not community_id:
            return None
        return f"https://{cp}.{self.HOST}/rental/community/{community_id}"

    # ─── HTML 解析 ───
    def parse_search(self, html: str, city: str) -> list[CommunityInfo]:
        """从安居客 community 列表页解析。

        典型结构：
          <div class="list-cell">
            <a class="li-row" href="https://shenzhen.anjuke.com/community/view/15028">
              ...小区名...
            </a>
            <div class="li-info">
              <h3>小区名</h3>
              <address>地址 [板块]</address>
              <strong>5.0 万/m²</strong>
            </div>
          </div>
        """
        out: list[CommunityInfo] = []
        if not html or len(html) < 1500:
            return out

        # 提取所有 community 链接 + 小区名
        # 实际 HTML 结构：
        #   <a href=".../community/view/{id}" class="li-row" ...>
        #     <div class="li-img"><img alt="{name}" src="..."></div>
        #     <div class="li-info"><div class="li-community-title">{name}</div>...</div>
        #   </a>
        # 用 img alt 提取最稳定（class 名经常改，alt 始终在）
        items = re.findall(
            r'href="[^"]*?/community/view/(\d+)"[^>]*>'
            r'.{0,300}?<img\s+alt="([^"]+)"',
            html, re.DOTALL
        )
        seen: set[str] = set()
        for cid, name in items:
            if cid in seen:
                continue
            seen.add(cid)
            name = name.strip()
            if not name or len(name) > 80:
                continue
            out.append(CommunityInfo(
                name=name,
                city=city,
                source=self.SITE_NAME,
                source_id=cid,
                url=self.community_detail_url(cid, city),
            ))

        return out

    def parse_community_detail(self, html: str, community_id: str,
                                city: str) -> CommunityInfo | None:
        """从详情页提取建成年份、户数、物业、地址。

        2026 年安居客详情页是 Vue.js SPA 渲染后 HTML，字段统一格式：
          <div class="label" data-v-...>建造年代</div>
          <div class="value" data-v-...>           2010年             </div>
        或带 hover 包装：
          <div class="label">{label}</div>
          <div class="hover" ...>
            <div class="value value_X" data-v-...>{value}</div>
            ...
          </div>
        """
        if not html or len(html) < 1500:
            return None

        kw: dict = {
            "name": "",
            "city": city,
            "source": self.SITE_NAME,
            "source_id": community_id,
            "url": self.community_detail_url(community_id, city),
        }

        # 小区名
        name_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if not name_match:
            name_match = re.search(r'<title>([^<]+?)[\-—_]', html)
        if name_match:
            kw["name"] = name_match.group(1).strip()

        # 通用 label-value 提取（兼容直接和 hover 包装）
        def _label_value(label_text: str) -> str | None:
            pattern = (
                r'<div class="label"[^>]*>\s*' + re.escape(label_text) + r'\s*</div>'
                r'\s*(?:<div class="hover"[^>]*>\s*)?'
                r'<div class="value[^"]*"[^>]*>\s*([^<]+?)\s*</div>'
            )
            m = re.search(pattern, html, re.DOTALL)
            if m:
                return m.group(1).strip().replace("&nbsp;", "")
            return None

        # 竣工时间："2012年" 或 "2012年、2013年、2014年"（分期）→ 取第一个 4 位数字
        finish = _label_value("竣工时间") or _label_value("建造年代") or _label_value("建成年代")
        if finish:
            year_match = re.search(r'(\d{4})', finish)
            if year_match:
                kw["built_year"] = int(year_match.group(1))

        # 总户数
        units = _label_value("总户数") or _label_value("户数")
        if units:
            n = re.search(r'(\d+)', units)
            if n:
                kw["unit_count"] = int(n.group(1))

        # 楼栋数
        bld = _label_value("总楼栋数") or _label_value("楼栋数") or _label_value("总栋数")
        if bld:
            n = re.search(r'(\d+)', bld)
            if n:
                kw["building_count"] = int(n.group(1))

        # 物业公司
        prop = _label_value("物业公司")
        if prop:
            kw["property_company"] = prop

        # 地址 — 优先「小区地址」，加上区前缀（anjuke 自己不带区）
        addr = _label_value("小区地址") or _label_value("地址")
        if addr:
            # anjuke 不含行政区前缀，作为前缀补全（如果列表 URL 是 longgang，就标 龙岗区）
            kw["address"] = addr

        # 至少要解出 name 或 built_year 才算成功
        if not kw["name"] and not kw.get("built_year"):
            return None
        return CommunityInfo(**kw)

    def parse_listings(self, html: str, community_id: str, city: str) -> PriceInfo:
        """从安居客租房列表聚合户型价格分布。

        安居客租房列表条目常见结构（简化）：
          <div class="zu-itemmod">
            <div class="zu-info">
              <h3>整租·XX小区 2室1厅 80㎡</h3>
              <p>价格 <strong>4500</strong> 元/月</p>
            </div>
          </div>
        """
        url = self.listings_url(community_id, city)
        if not html or len(html) < 1500:
            return PriceInfo(community_id=community_id, source=self.SITE_NAME, url=url)

        by_room: dict[int, dict] = {1: {"prices": [], "count": 0},
                                    2: {"prices": [], "count": 0},
                                    3: {"prices": [], "count": 0}}
        shared = {"prices": [], "count": 0}

        # 列表项；尝试多种结构
        items = re.findall(
            r'<div[^>]+class="(?:zu-itemmod|list-item|property)[^"]*"[^>]*>(.*?)</div>\s*</div>',
            html, re.DOTALL,
        )
        for raw in items:
            is_shared = "合租" in raw or "主卧" in raw
            room_match = re.search(r'(\d+)\s*[室房]', raw)
            price_match = re.search(r'(?:<strong>|<em>|<b>)\s*(\d{3,5})\s*(?:</strong>|</em>|</b>)', raw)
            if not price_match:
                continue
            price = int(price_match.group(1))
            # 排除明显不对的总价（百万级）
            if price < 500 or price > 30000:
                continue
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

        total = sum(d["count"] for d in [*by_room.values(), shared])
        return PriceInfo(
            community_id=community_id,
            source=self.SITE_NAME,
            url=url,
            by_room={
                "one_bedroom": _summarize(by_room[1]),
                "two_bedroom": _summarize(by_room[2]),
                "three_bedroom": _summarize(by_room[3]),
                "shared_room": _summarize(shared),
            },
            total_listings=total,
        )


register(AnjukeAdapter())
