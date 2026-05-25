"""Ziroom (自如 ziroom.com) adapter — 长租公寓品牌（KE Holdings 旗下）。

核心价值：**合租主卧/次卧** 价格（链家弱项 — 链家以整租为主）。

URL 模式：
  - 城市列表：https://{cp}.ziroom.com/z/                  ← 整租
  - 合租列表：https://{cp}.ziroom.com/hezu/               ← 合租主卧
  - 区过滤：  https://{cp}.ziroom.com/z/c{cid}/           ← 城市/区编号
  - 详情页：  https://www.ziroom.com/x/{rid}.html
  cp = 城市拼音（shenzhen / shanghai / beijing / guangzhou 等）
  注意：ziroom 不按"小区"组织数据，按"房源"组织。所以"小区"概念上要从房源聚合反推。

实施策略：
  - search_community_url: 用列表页 URL（按区过滤）
  - parse_search: 从列表 li 元素聚合"按小区"分组（resblock_name 字段）
  - community_detail_url: ziroom 没有"小区详情页"概念，返 None（让 fallback 走别的源）
  - listings_url: 按"小区名字关键词搜索" URL
  - parse_listings: 解析挂牌，区分整租/合租，按户型聚合
"""
from __future__ import annotations

import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sources.site_adapters import (  # type: ignore
    CommunityInfo, PriceInfo, register,
)


# ziroom 用全拼音做城市子域
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
    "苏州市": "su",  "苏州": "su",
}


class ZiroomAdapter:
    SITE_NAME = "ziroom"
    HOST = "ziroom.com"
    SUPPORTED_CITIES = set(_CITY_PINYIN.keys())

    def _cp(self, city: str) -> str | None:
        return _CITY_PINYIN.get(city)

    # ─── URL 构造 ───
    def search_community_url(self, city: str, district: str | None) -> str | None:
        cp = self._cp(city)
        if not cp:
            return None
        # 自如不按行政区组织，用关键词搜
        if district:
            return f"https://{cp}.{self.HOST}/z/?keyword={urllib.parse.quote(district)}"
        return f"https://{cp}.{self.HOST}/z/"

    def community_detail_url(self, community_id: str, city: str) -> str | None:
        # 自如没有"小区"维度的详情页（建成年份等字段它也没有）
        return None

    def listings_url(self, community_id: str, city: str) -> str | None:
        """这里 community_id 可以是小区名字（不是数字 id）。用关键词搜索。"""
        cp = self._cp(city)
        if not cp or not community_id:
            return None
        return f"https://{cp}.{self.HOST}/z/?keyword={urllib.parse.quote(community_id)}"

    # ─── HTML 解析 ───
    def parse_search(self, html: str, city: str) -> list[CommunityInfo]:
        """从列表页聚合出"包含房源的小区列表"。

        自如列表 li 结构（2024-2026 常见版）：
          <div class="info-box">
            <h5><a target="_blank" href="//www.ziroom.com/x/123.html"
                   title="自如·XX小区 整租 2居室 ...">...</a></h5>
            <div class="desc"><div>...</div>
              <p class="desc--apartment">XX小区 / 区/商圈 / 离地铁 X 米</p>
            </div>
            <div class="price"><span>¥3500</span> /月（季付价）</div>
          </div>

        我们按 desc--apartment 里的"小区名"分组聚合。
        """
        out: list[CommunityInfo] = []
        if not html or len(html) < 1500:
            return out

        items = re.findall(
            r'<div[^>]+class="info-box[^"]*"[^>]*>(.*?)</div>\s*</div>',
            html, re.DOTALL,
        )

        # 聚合：community_name → 房源列表
        by_resblock: dict[str, dict] = {}
        for raw in items:
            title_match = re.search(r'title="([^"]+)"', raw)
            apt_match = re.search(
                r'class="desc--apartment"[^>]*>([^<]+)<',
                raw,
            )
            price_match = re.search(r'<span[^>]*>¥?\s*(\d+)\s*</span>', raw)
            if not (title_match or apt_match):
                continue

            # 小区名提取：从 desc--apartment 第一段
            resblock = None
            if apt_match:
                parts = re.split(r'\s*[/／]\s*', apt_match.group(1).strip())
                if parts:
                    resblock = parts[0].strip()

            if not resblock and title_match:
                # 从 title 抠：去掉自如· 前缀，按空格切
                title = title_match.group(1)
                title = title.replace("自如·", "").strip()
                resblock = title.split(" ")[0] if title else None

            if not resblock:
                continue

            agg = by_resblock.setdefault(resblock, {
                "prices": [],
                "count": 0,
            })
            agg["count"] += 1
            if price_match:
                agg["prices"].append(int(price_match.group(1)))

        for name, agg in by_resblock.items():
            rent_avg = round(sum(agg["prices"]) / len(agg["prices"])) if agg["prices"] else None
            out.append(CommunityInfo(
                name=name,
                city=city,
                source=self.SITE_NAME,
                source_id=name,  # 自如用名字作 id（关键词搜）
                listings_count=agg["count"],
                rent_avg=rent_avg,
            ))

        return out

    def parse_community_detail(self, html: str, community_id: str,
                                city: str) -> CommunityInfo | None:
        # 自如没有"小区详情"概念，直接 None
        return None

    def parse_listings(self, html: str, community_id: str, city: str) -> PriceInfo:
        """从列表 HTML 聚合该小区的整租/合租价格分布。"""
        url = self.listings_url(community_id, city)
        if not html or len(html) < 1500:
            return PriceInfo(community_id=community_id, source=self.SITE_NAME, url=url)

        by_room: dict[int, dict] = {1: {"prices": [], "count": 0},
                                    2: {"prices": [], "count": 0},
                                    3: {"prices": [], "count": 0}}
        shared = {"prices": [], "count": 0}

        items = re.findall(
            r'<div[^>]+class="info-box[^"]*"[^>]*>(.*?)</div>\s*</div>',
            html, re.DOTALL,
        )
        for raw in items:
            title_match = re.search(r'title="([^"]+)"', raw)
            price_match = re.search(r'<span[^>]*>¥?\s*(\d+)\s*</span>', raw)
            if not (title_match and price_match):
                continue

            title = title_match.group(1)
            price = int(price_match.group(1))

            # 严格匹配该小区（避免列表里混入其他小区房源）
            if community_id and community_id not in title:
                continue

            # 合租识别：自如标题"自如·X小区 合租 Y居室 卧室名" 或 "整租"
            if "合租" in title or "卧" in title:
                shared["prices"].append(price)
                shared["count"] += 1
                continue

            # 整租户型识别："2居室" / "2室1厅"
            room_match = re.search(r'(\d+)\s*[居室]', title)
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


register(ZiroomAdapter())
