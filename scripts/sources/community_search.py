"""候选小区生成 — 链家精细数据 + 百度地图 POI 全国通用兜底。

策略：
  1. 城市在 rental.CITY_PINYIN 白名单 → 走 rental.top_communities（精细：户型/挂牌量/均价）
  2. 不在白名单 / 链家失败 → 走 baidu_map fallback（POI 关键词搜「{city} {district} 小区」）
"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import cached  # type: ignore
from sources import rental, baidu_map, amap, tianditu  # type: ignore


def find_candidates(city: str, district: str | None = None,
                    area: str | None = None,
                    limit: int = 10,
                    search_radius_m: int | None = None) -> tuple[list[dict], str]:
    """生成候选小区列表。

    两种语义：
      1. **行政区搜索**（area=None）：housing_bridge → 链家直爬 → 百度兜底（5km）
      2. **中心点搜索**（area=小区名/商圈）：直接百度 nearby，半径默认 1000m

    Returns:
        (communities, source_label)
        source_label ∈ {"ke_full", "lianjia_full", "anjuke_full", ...,
                        "baidu_map_poi", "amap_poi", "tianditu_poi", "empty"}
    """
    # 中心点搜索：area 非空 = 直接走百度 nearby
    if area:
        if search_radius_m is None:
            search_radius_m = 1000  # 中心点默认 1km
    else:
        # 行政区搜索
        # 1. Housing Bridge（最强，绕反爬，多站点 fallback）
        try:
            from sources import housing_bridge  # type: ignore
            if housing_bridge.is_bridge_running():
                cinfos, source_used = housing_bridge.search_communities(
                    city, district, limit=limit,
                )
                if cinfos:
                    dicts = [_community_info_to_dict(c) for c in cinfos]
                    return dicts, f"{source_used}_full"
        except Exception:
            pass

        # 2. 链家直爬（保留直爬路径作 fallback）
        if rental.is_lianjia_supported(city):
            communities = rental.top_communities(city, district, limit=limit)
            if communities:
                return communities, "lianjia_full"

        # 3. 行政区无法精细查时，用 5km 半径兜底
        search_radius_m = 5000

    # 百度地图 nearby 搜索（中心点 + 半径）
    location_text = f"{city}{district or ''}{area or ''}"
    geo = (baidu_map.geocode(location_text)
           or amap.geocode(location_text)
           or tianditu.geocode(location_text))
    if not geo:
        return [], "empty"

    keywords_to_try = ["小区", "花园", "公寓", "苑"]
    found: dict[str, dict] = {}
    used_source = None

    for kw in keywords_to_try:
        # 三家 fallback：百度 → 高德 → 天地图
        results = baidu_map.search_nearby(kw, geo["lat"], geo["lng"], search_radius_m, page_size=20)
        source = "baidu_map_poi"
        if not results:
            results = amap.search_nearby(kw, geo["lat"], geo["lng"], search_radius_m, page_size=25)
            source = "amap_poi" if results else source
        if not results:
            results = tianditu.search_nearby(kw, geo["lat"], geo["lng"], search_radius_m, page_size=20)
            source = "tianditu_poi" if results else source
        used_source = used_source or (source if results else None)

        for r in (results or []):
            uid = r.get("uid") or r.get("name")
            if not uid or uid in found:
                continue
            # 1) residential 类型过滤
            type_str = (str(r.get("type") or "") + str(r.get("tag") or "")).lower()
            name = r.get("name") or ""
            is_residential = (
                "house" in type_str
                or "住宅" in type_str
                or "住宿" in type_str
                or "公寓" in type_str
                or "小区" in type_str
                or any(s in name for s in [
                    "小区", "花园", "城", "公寓", "苑", "府", "湾",
                    "庭", "邸", "园", "里", "村", "家园", "新村",
                ])
            )
            if not is_residential:
                continue
            # 2) 严格 district 过滤：当 search_nearby 越界时（rare），地址里必须含 district 名
            if district:
                addr = (str(r.get("address") or "") + str(r.get("area") or ""))
                # district 缩写也算（如「坪山区」匹配「坪山」）
                short_district = district.rstrip("区县市")
                if district not in addr and short_district not in addr:
                    continue
            found[uid] = {
                "id": f"{source}-{uid}",
                "name": r.get("name"),
                "city": city,
                "district": district or r.get("area"),
                "address": r.get("address"),
                "lat": r.get("lat"),
                "lng": r.get("lng"),
                "source": source,
                "url": None,
                "rent_avg": None,  # 无租金数据
                "listings": None,
            }
            if len(found) >= limit:
                break
        if len(found) >= limit:
            break

    if found:
        return list(found.values())[:limit], used_source or "amap_poi"
    return [], "empty"


def _community_info_to_dict(info) -> dict:
    """把 CommunityInfo dataclass 转成 community_search 输出的 dict 格式。"""
    return {
        "id": info.source_id or info.name,  # 链家数字 id 直接用
        "name": info.name,
        "city": info.city,
        "district": info.district,
        "address": info.address,
        "lat": info.lat,
        "lng": info.lng,
        "source": info.source,
        "url": info.url,
        "rent_avg": info.rent_avg,
        "listings": info.listings_count,
        # 提前补建成年份等元数据（如果 adapter 已经抓到）
        "built_year": info.built_year,
        "building_count": info.building_count,
        "unit_count": info.unit_count,
        "property_company": info.property_company,
    }
