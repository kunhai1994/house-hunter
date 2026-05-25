"""Lianjia (链家) adapter — KE Holdings 自营中介，深圳挂牌量最大。

URL 模式：
  - 小区列表：https://{cp}.lianjia.com/xiaoqu/{dp}/        ← 按区挂牌量排序
  - 小区详情：https://{cp}.lianjia.com/xiaoqu/{id}/         ← 含建成年份、户数、物业
  - 租房列表：https://{cp}.lianjia.com/zufang/c{id}/        ← 按户型聚合价格
  cp = 城市拼音（如 "sz"），dp = 区拼音（如 "longgang"），id = 数字小区 id

复用现有 rental.py 已经实测过的正则解析。
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sources.site_adapters import (  # type: ignore
    CommunityInfo, PriceInfo, register,
)


# ───────────────────────── 城市/区 拼音映射 ─────────────────────────
# 主要城市（详细映射跟 rental.py 共享，避免重复维护，import 自 rental）
def _city_pinyin(city: str) -> str | None:
    from sources import rental  # type: ignore
    return rental.city_pinyin(city)


def _district_pinyin(city: str, district: str) -> str | None:
    from sources import rental  # type: ignore
    return rental.district_pinyin(city, district)


# ───────────────────────── Adapter 类 ─────────────────────────
class LianjiaAdapter:
    SITE_NAME = "lianjia"
    HOST = "lianjia.com"

    @property
    def SUPPORTED_CITIES(self) -> set[str]:
        from sources import rental  # type: ignore
        return set(rental.CITY_PINYIN.keys())

    # ─── URL 构造 ───
    def search_community_url(self, city: str, district: str | None) -> str | None:
        cp = _city_pinyin(city)
        if not cp:
            return None
        if district:
            dp = _district_pinyin(city, district)
            if dp:
                return f"https://{cp}.{self.HOST}/xiaoqu/{dp}/"
        return f"https://{cp}.{self.HOST}/xiaoqu/"

    def community_detail_url(self, community_id: str, city: str) -> str | None:
        cp = _city_pinyin(city)
        if not cp or not community_id:
            return None
        return f"https://{cp}.{self.HOST}/xiaoqu/{community_id}/"

    def listings_url(self, community_id: str, city: str) -> str | None:
        cp = _city_pinyin(city)
        if not cp or not community_id:
            return None
        return f"https://{cp}.{self.HOST}/zufang/c{community_id}/"

    # ─── HTML 解析 ───
    def parse_search(self, html: str, city: str) -> list[CommunityInfo]:
        """从 xiaoqu/{district}/ 列表页解析小区清单。"""
        out: list[CommunityInfo] = []

        # 链家 xiaoqu 列表项常见结构：
        # <li class="clear xiaoquListItem" data-id="2123" ...>
        #   <div class="info">
        #     <div class="title"><a href="/xiaoqu/2123/">某某小区</a></div>
        #     <div class="positionInfo"><a href="/xiaoqu/longgang/...">龙岗</a>...</div>
        #     <div class="totalPrice"><span>5.0</span>万/㎡</div>
        #     ...
        items = re.findall(
            r'<li[^>]*class="[^"]*xiaoquListItem[^"]*"[^>]*data-id="(\d+)"[^>]*>(.*?)</li>',
            html, re.DOTALL,
        )
        for cid, raw in items:
            name_match = re.search(
                r'<div class="title">\s*<a[^>]*>([^<]+)</a>',
                raw,
            )
            if not name_match:
                continue
            name = name_match.group(1).strip()

            district = None
            district_match = re.search(
                r'<a[^>]+href="/xiaoqu/[a-z]+/"[^>]*>([^<]+)</a>',
                raw,
            )
            if district_match:
                district = district_match.group(1).strip()

            listings_count = None
            listings_match = re.search(r'在租(\d+)套', raw)
            if listings_match:
                listings_count = int(listings_match.group(1))

            out.append(CommunityInfo(
                name=name,
                city=city,
                source=self.SITE_NAME,
                source_id=cid,
                url=f"https://{_city_pinyin(city)}.{self.HOST}/xiaoqu/{cid}/",
                district=district,
                listings_count=listings_count,
            ))

        # 部分页面用旧版结构（content__list--item--main 嵌套），fallback 解析
        if not out:
            out = self._parse_search_fallback(html, city)

        return out

    def _parse_search_fallback(self, html: str, city: str) -> list[CommunityInfo]:
        """老版 / zufang 列表页结构 fallback。"""
        out: list[CommunityInfo] = []
        items = re.findall(
            r'<div class="content__list--item--main">(.*?)</div>\s*</div>',
            html, re.DOTALL,
        )
        seen: set[str] = set()
        for raw in items:
            name_match = re.search(
                r'<a[^>]+href="(/xiaoqu/(\d+)/?)"[^>]*>([^<]+)</a>',
                raw,
            )
            if not name_match:
                continue
            cid = name_match.group(2)
            if cid in seen:
                continue
            seen.add(cid)
            name = name_match.group(3).strip()
            out.append(CommunityInfo(
                name=name,
                city=city,
                source=self.SITE_NAME,
                source_id=cid,
                url=f"https://{_city_pinyin(city)}.{self.HOST}/xiaoqu/{cid}/",
            ))
        return out

    def parse_community_detail(self, html: str, community_id: str,
                                city: str) -> CommunityInfo | None:
        """从 xiaoqu/{id}/ 详情页解析建成年份、楼栋、户数、物业、经纬度。"""
        if not html or len(html) < 1500:
            return None

        info_kwargs: dict = {
            "name": "",
            "city": city,
            "source": self.SITE_NAME,
            "source_id": community_id,
            "url": self.community_detail_url(community_id, city),
        }

        name_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if name_match:
            info_kwargs["name"] = name_match.group(1).strip()

        # 详情页字段对（label, value）
        pairs = re.findall(
            r'<span class="xiaoquInfoLabel">([^<]+)</span>\s*'
            r'<span class="xiaoquInfoContent[^"]*"[^>]*>([^<]+)</span>',
            html,
        )
        for label, value in pairs:
            v = value.strip().replace("&nbsp;", "")
            if "建成年代" in label or "建筑年代" in label:
                ym = re.search(r'(\d{4})', v)
                if ym:
                    info_kwargs["built_year"] = int(ym.group(1))
            elif "楼栋总数" in label:
                n = re.search(r'(\d+)', v)
                if n:
                    info_kwargs["building_count"] = int(n.group(1))
            elif "房屋总数" in label:
                n = re.search(r'(\d+)', v)
                if n:
                    info_kwargs["unit_count"] = int(n.group(1))
            elif "物业公司" in label:
                info_kwargs["property_company"] = v

        # 地址（多种结构兼容：detailDesc / address 标签）
        addr_match = (
            re.search(r'<div class="detailDesc"[^>]*>([^<]+)</div>', html)
            or re.search(r'<div class="xiaoquAddress"[^>]*>\s*<span[^>]*>地址[:：]?</span>\s*([^<]+?)\s*<', html)
            or re.search(r'地\s*址[：:]\s*</[a-z]+>\s*<[a-z]+[^>]*>([^<]{4,80})', html)
        )
        if addr_match:
            info_kwargs["address"] = addr_match.group(1).strip().replace("&nbsp;", "")

        # 经纬度（用于地图查询的回退）
        loc_match = re.search(
            r"resblockPosition[\"']?\s*[:=]\s*[\"']([^,\"']+),([^\"']+)[\"']",
            html,
        )
        if loc_match:
            try:
                info_kwargs["lng"] = float(loc_match.group(1))
                info_kwargs["lat"] = float(loc_match.group(2))
            except ValueError:
                pass

        # 至少要解出 name 或者一个元数据字段才算成功
        if not info_kwargs["name"] and not info_kwargs.get("built_year"):
            return None

        return CommunityInfo(**info_kwargs)

    def parse_listings(self, html: str, community_id: str, city: str) -> PriceInfo:
        """从 zufang/c{id}/ 解析每户型的均价 + 挂牌量。"""
        url = self.listings_url(community_id, city)
        if not html or len(html) < 1500:
            return PriceInfo(community_id=community_id, source=self.SITE_NAME, url=url)

        by_room: dict[int, dict] = {1: {"prices": [], "count": 0},
                                    2: {"prices": [], "count": 0},
                                    3: {"prices": [], "count": 0}}
        shared = {"prices": [], "count": 0}

        items = re.findall(
            r'<div class="content__list--item--main">(.*?)</div>\s*</div>',
            html, re.DOTALL,
        )
        for raw in items:
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


# 注册
register(LianjiaAdapter())
