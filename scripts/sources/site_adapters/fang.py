"""Fang (房天下 fang.com) adapter — 老牌房产门户。

URL 模式：
  - 城市子域：{cp}.fang.com（深圳 sz、上海 sh、北京 bj、广州 gz）
  - 二手房城市站：esf.{cp}.fang.com
  - 租房城市站：  zu.{cp}.fang.com
  - 小区库：    https://esf.{cp}.fang.com/housing/
  - 按区：      https://esf.{cp}.fang.com/housing/__1_{district_id}_0_0_1_0_0_0_0/
  - 详情：     https://{community_pinyin}.fang.com  ← 房天下每个小区有独立子域名
  - 详情简单版：https://esf.{cp}.fang.com/chushou/3_{community_id}.htm

注意：
  - 房天下偏新房/买房视角，对租房 skill 价值次于链家
  - 字段相对全：建成年代、楼栋数、物业公司、绿化率等
  - 反爬中等强度
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sources.site_adapters import (  # type: ignore
    CommunityInfo, PriceInfo, register,
)


_CITY_PINYIN = {
    "深圳市": "sz",  "深圳": "sz",
    "上海市": "sh",  "上海": "sh",
    "北京市": "bj",  "北京": "bj",
    "广州市": "gz",  "广州": "gz",
    "杭州市": "hz",  "杭州": "hz",
    "成都市": "cd",  "成都": "cd",
    "武汉市": "wuhan", "武汉": "wuhan",
    "南京市": "nanjing", "南京": "nanjing",
    "天津市": "tj",  "天津": "tj",
    "重庆市": "cq",  "重庆": "cq",
    "苏州市": "suzhou", "苏州": "suzhou",
}


class FangAdapter:
    SITE_NAME = "fang"
    HOST = "fang.com"
    SUPPORTED_CITIES = set(_CITY_PINYIN.keys())

    def _cp(self, city: str) -> str | None:
        return _CITY_PINYIN.get(city)

    # ─── URL 构造 ───
    def search_community_url(self, city: str, district: str | None) -> str | None:
        cp = self._cp(city)
        if not cp:
            return None
        # 二手房子域的小区库
        if district:
            return f"https://esf.{cp}.{self.HOST}/housing/?keyword={district}"
        return f"https://esf.{cp}.{self.HOST}/housing/"

    def community_detail_url(self, community_id: str, city: str) -> str | None:
        cp = self._cp(city)
        if not cp or not community_id:
            return None
        # 房天下的小区详情常见 URL 模式
        return f"https://esf.{cp}.{self.HOST}/chushou/3_{community_id}.htm"

    def listings_url(self, community_id: str, city: str) -> str | None:
        cp = self._cp(city)
        if not cp or not community_id:
            return None
        # 该小区的租房列表
        return f"https://zu.{cp}.{self.HOST}/house/h318-i3{community_id}/"

    # ─── HTML 解析 ───
    def parse_search(self, html: str, city: str) -> list[CommunityInfo]:
        """从房天下小区库解析。"""
        out: list[CommunityInfo] = []
        if not html or len(html) < 1500:
            return out

        # 房天下小区链接形如 /chushou/3_{id}.htm
        items = re.findall(
            r'href="(?:https?://[^/]+)?/chushou/3_(\d+)\.htm"[^>]*>\s*([^<]+?)\s*<',
            html,
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

        # 房天下字段表（典型 dl/dt/dd 或 li/span 结构）
        for label, regex in [
            ("built_year", r'(?:建筑年代|建成年代|竣工时间|年代)[:：\s<>"a-z]*(\d{4})'),
            ("unit_count", r'(?:总户数|户数|总套数)[:：\s<>"a-z]*(\d+)\s*[户套]'),
            ("building_count", r'(?:总楼栋|楼栋数|栋数)[:：\s<>"a-z]*(\d+)\s*[栋幢]'),
        ]:
            m = re.search(regex, html)
            if m:
                kw[label] = int(m.group(1))

        prop_match = re.search(r'物业公司[:：\s<>"a-z]*([^<>\s]+(?:[^<>\n]{0,40}[^<>\s])?)', html)
        if prop_match:
            kw["property_company"] = prop_match.group(1).strip()

        if not kw["name"] and not kw.get("built_year"):
            return None
        return CommunityInfo(**kw)

    def parse_listings(self, html: str, community_id: str, city: str) -> PriceInfo:
        """从房天下租房列表聚合。"""
        url = self.listings_url(community_id, city)
        if not html or len(html) < 1500:
            return PriceInfo(community_id=community_id, source=self.SITE_NAME, url=url)

        by_room: dict[int, dict] = {1: {"prices": [], "count": 0},
                                    2: {"prices": [], "count": 0},
                                    3: {"prices": [], "count": 0}}
        shared = {"prices": [], "count": 0}

        # 房天下房源条目
        items = re.findall(
            r'<dl[^>]*class="(?:list rel|houseList)[^"]*"[^>]*>(.*?)</dl>',
            html, re.DOTALL,
        )
        if not items:
            items = re.findall(
                r'<div[^>]+class="(?:houseList|house-list|list-item)[^"]*"[^>]*>(.*?)</div>\s*</div>',
                html, re.DOTALL,
            )

        for raw in items:
            is_shared = "合租" in raw or "床位" in raw
            room_match = re.search(r'(\d+)\s*[室房]', raw)
            price_match = (
                re.search(r'<(?:span|p|em|b)[^>]*class="[^"]*price[^"]*"[^>]*>\s*(\d{3,5})', raw)
                or re.search(r'(\d{3,5})\s*元/月', raw)
            )
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


register(FangAdapter())
