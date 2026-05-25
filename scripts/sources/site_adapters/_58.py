"""58 同城 (58.com) 房产频道 adapter — 综合分类信息，个人房东直租为主。

URL 模式（2024-2026 常见）：
  - 城市子域：{cp}.58.com（深圳=sz）
  - 租房：    https://sz.58.com/chuzu/
  - 按区：    https://sz.58.com/longgang/chuzu/
  - 二手房：  https://sz.58.com/ershoufang/
  - 小区库：  https://sz.58.com/xiaoqu/
  - 小区详情：https://sz.58.com/xiaoqu/{id}/  或  https://sz.58.com/xiaoqu/?xq={id}

特点：
  - 58 系跟 anjuke 共一套反爬，需登录
  - HTML 模板最杂乱，多套版本并存
  - 个人房东信息覆盖广，但质量参差
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sources.site_adapters import (  # type: ignore
    CommunityInfo, PriceInfo, register,
)

# 58 同城用短拼音子域（部分跟链家相同）
_CITY_PINYIN = {
    "深圳市": "sz",  "深圳": "sz",
    "上海市": "sh",  "上海": "sh",
    "北京市": "bj",  "北京": "bj",
    "广州市": "gz",  "广州": "gz",
    "杭州市": "hz",  "杭州": "hz",
    "成都市": "cd",  "成都": "cd",
    "武汉市": "wh",  "武汉": "wh",
    "南京市": "nj",  "南京": "nj",
    "天津市": "tj",  "天津": "tj",
    "重庆市": "cq",  "重庆": "cq",
    "苏州市": "su",  "苏州": "su",
    "西安市": "xa",  "西安": "xa",
    "长沙市": "cs",  "长沙": "cs",
    "郑州市": "zz",  "郑州": "zz",
}

_DISTRICT_PINYIN = {
    ("深圳市", "南山区"): "nanshanqu",
    ("深圳市", "福田区"): "futianqu",
    ("深圳市", "罗湖区"): "luohuqu",
    ("深圳市", "宝安区"): "baoanqu",
    ("深圳市", "龙岗区"): "longgangqu",
    ("深圳市", "龙华区"): "longhuaqu",
    ("深圳市", "坪山区"): "pingshanqu",
    ("深圳市", "光明区"): "guangmingxinqu",
    ("深圳市", "盐田区"): "yantianqu",
}


class WubaAdapter:
    """58 = wuba（无霸）"""
    SITE_NAME = "58"
    HOST = "58.com"
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
            # 区级小区库
            return f"https://{cp}.{self.HOST}/{dp}/xiaoqu/"
        return f"https://{cp}.{self.HOST}/xiaoqu/"

    def community_detail_url(self, community_id: str, city: str) -> str | None:
        cp = self._cp(city)
        if not cp or not community_id:
            return None
        # 58 的小区详情格式有两种，先尝试 path 形式
        return f"https://{cp}.{self.HOST}/xiaoqu/{community_id}x.shtml"

    def listings_url(self, community_id: str, city: str) -> str | None:
        cp = self._cp(city)
        if not cp or not community_id:
            return None
        # 该小区的租房挂牌
        return f"https://{cp}.{self.HOST}/chuzu/?key={community_id}"

    # ─── HTML 解析 ───
    def parse_search(self, html: str, city: str) -> list[CommunityInfo]:
        """从 58 小区库列表解析。58 模板多变，用宽松正则。"""
        out: list[CommunityInfo] = []
        if not html or len(html) < 1500:
            return out

        # 形如 href="/xiaoqu/12345x.shtml">XX小区</a>
        items = re.findall(
            r'href="(?:https?://[^/]+)?/xiaoqu/(\d+)x?\.shtml"[^>]*>\s*([^<]+?)\s*<',
            html,
        )
        seen: set[str] = set()
        for cid, name in items:
            if cid in seen:
                continue
            seen.add(cid)
            name = name.strip()
            if not name or len(name) > 80 or "更多" in name:
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
        """从 58 小区详情解析。"""
        if not html or len(html) < 1500:
            return None

        kw: dict = {
            "name": "",
            "city": city,
            "source": self.SITE_NAME,
            "source_id": community_id,
            "url": self.community_detail_url(community_id, city),
        }

        name_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if not name_match:
            name_match = re.search(r'<title>([^<]+?)[\-—_]', html)
        if name_match:
            kw["name"] = name_match.group(1).strip()

        # 58 字段表（多种格式并存）
        for label, regex in [
            ("built_year", r'(?:建筑年代|建成年代|年代|竣工时间)[:：\s<>"a-z]*(\d{4})'),
            ("unit_count", r'(?:总户数|户数)[:：\s<>"a-z]*(\d+)'),
            ("building_count", r'(?:总栋数|楼栋|栋数)[:：\s<>"a-z]*(\d+)'),
        ]:
            m = re.search(regex, html)
            if m:
                kw[label] = int(m.group(1))

        prop_match = re.search(r'(?:物业公司|物业)[:：\s<>"a-z]*([^<>\s]+(?:[^<>\n]{0,40}[^<>\s])?)', html)
        if prop_match:
            kw["property_company"] = prop_match.group(1).strip()

        if not kw["name"] and not kw.get("built_year"):
            return None
        return CommunityInfo(**kw)

    def parse_listings(self, html: str, community_id: str, city: str) -> PriceInfo:
        """从 58 租房列表聚合。58 个人房东居多，质量参差。"""
        url = self.listings_url(community_id, city)
        if not html or len(html) < 1500:
            return PriceInfo(community_id=community_id, source=self.SITE_NAME, url=url)

        by_room: dict[int, dict] = {1: {"prices": [], "count": 0},
                                    2: {"prices": [], "count": 0},
                                    3: {"prices": [], "count": 0}}
        shared = {"prices": [], "count": 0}

        # 58 列表项尝试多种结构
        items = re.findall(
            r'<li[^>]*(?:class="house-cell"|class="house-list-item")[^>]*>(.*?)</li>',
            html, re.DOTALL,
        )
        if not items:
            # 备选：纯 div 包装
            items = re.findall(
                r'<div[^>]+(?:class="[^"]*item[^"]*"|class="[^"]*list[^"]*house[^"]*")[^>]*>(.*?)</div>\s*</div>',
                html, re.DOTALL,
            )

        for raw in items:
            is_shared = "合租" in raw or "床位" in raw
            room_match = re.search(r'(\d+)\s*[室房]', raw)
            # 58 价格可能在 <b class="pri">3500</b>
            price_match = re.search(
                r'<(?:b|strong|em|span)[^>]*class="[^"]*(?:pri|money|sum)[^"]*"[^>]*>\s*(\d{3,5})',
                raw,
            ) or re.search(r'(\d{3,5})\s*元/月', raw)
            if not price_match:
                continue
            price = int(price_match.group(1))
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


register(WubaAdapter())
