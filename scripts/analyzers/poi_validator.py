"""POI 多类别校验。

输入：候选小区列表 + must/nice POI 规格
处理：对每个小区并行查询所有类别（百度主，高德回退）
输出：每个小区的 POI 校验报告
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import parallel_map, haversine, get_config  # type: ignore
from sources import baidu_map, amap, tianditu  # type: ignore


def _matches_expected_tags(poi: dict, expected_tags: list[str]) -> bool:
    """关键 POI 类型校验：百度的 tag/type 字段（'购物;超市'）必须含 expected_tags 之一。

    expected_tags 由 config/poi_categories.yaml 的 expected_tags 字段给出。
    例：搜「山姆」碰到「山姆大叔少儿英语」（tag=教育培训），expected_tags=[超市, 仓储会员店]
        → 不命中，过滤掉。

    没设 expected_tags（旧 spec）→ 跳过此校验，回退到 keyword 匹配。
    """
    if not expected_tags:
        return True  # 不强制
    tag = (poi.get("tag") or "")
    type_str = (poi.get("type") or "")
    haystack = f"{tag} {type_str}".lower()
    return any(t.lower() in haystack for t in expected_tags)


def _is_relevant_to_keyword(poi: dict, keyword: str) -> bool:
    """二次过滤：百度/高德的 search_nearby 经常返回模糊匹配（搜「地铁站」返回宾馆）。
    只保留 name / type / tag 中真的含 keyword 的 POI。"""
    name = poi.get("name") or ""
    tag = poi.get("tag") or ""
    type_str = poi.get("type") or ""
    haystack = f"{name} {tag} {type_str}".lower()
    kw_lower = keyword.lower()

    # 直接包含
    if kw_lower in haystack:
        return True

    # 单字母品牌/字符（如 "Ole" "IMAX" "CGV"）
    if re.search(rf"\b{re.escape(kw_lower)}\b", haystack):
        return True

    return False


def _detect_brand(poi: dict, brand_keywords: list[str]) -> list[str]:
    """在 POI 名字中识别命中的品牌，用于报告显示（不影响 API 调用）。"""
    if not brand_keywords:
        return []
    name_lower = (poi.get("name") or "").lower()
    return [b for b in brand_keywords if b.lower() in name_lower]


def _search_pois_for_spec(spec: dict, lat: float, lng: float) -> list[dict]:
    """根据 spec.search_keywords + radius 搜索 POI。

    优化（v2，2026-05）：
      - 只用 search_keywords（通常 1-3 个泛用词如「超市」「电影院」）调 API
      - 不再每个品牌名（山姆/沃尔玛/...）单独调 API ← 配额省 5-10x
      - 拿到 POI 后，用 expected_tags 强过滤 + brand_keywords 标记品牌
      - must_have_brand 用 brand_keywords 子集过滤
    """
    radius = spec.get("radius_m", 3000)
    # 优先 search_keywords（新 schema），回退到 keywords（旧 schema 兼容）
    search_kws = spec.get("search_keywords") or spec.get("keywords") or []
    brand_kws = spec.get("brand_keywords") or []
    expected_tags = spec.get("expected_tags") or []
    must_have_brand = spec.get("must_have_brand") or []

    if not search_kws:
        return []

    found: dict[str, dict] = {}  # 按 uid 去重
    for kw in search_kws:
        # 三家 fallback：百度（5000/天） → 高德（100/天） → 天地图（10000/天）
        results = baidu_map.search_nearby(kw, lat, lng, radius, page_size=20)
        if not results:
            results = amap.search_nearby(kw, lat, lng, radius, page_size=25)
        if not results:
            results = tianditu.search_nearby(kw, lat, lng, radius, page_size=20)
        for r in results or []:
            uid = r.get("uid") or f"{r.get('name')}@{r.get('lat')},{r.get('lng')}"
            if uid in found:
                continue
            # 强过滤 1：tag/type 必须命中类别预期（避免「山姆大叔少儿英语」）
            if not _matches_expected_tags(r, expected_tags):
                continue
            # 强过滤 2：name/tag/type 含 search keyword
            if not _is_relevant_to_keyword(r, kw):
                continue
            r["matched_keyword"] = kw
            # 品牌识别（不调 API，纯字符串匹配）：用于报告显示
            r["matched_brand"] = _detect_brand(r, brand_kws)
            # must_have_brand 严格过滤（仅当用户指定了品牌要求）
            if must_have_brand:
                brand_hits = _detect_brand(r, must_have_brand)
                if not brand_hits:
                    continue
                r["matched_brand"] = brand_hits
            found[uid] = r

    items = list(found.values())
    items.sort(key=lambda x: x.get("distance_m", 1e9))
    return items


def validate_community(community: dict, must_have: list[dict],
                       nice_to_have: list[dict]) -> dict:
    """单个小区的 POI 校验。

    Args:
      community: {"id","name","city","district","lat","lng",...}
      must_have / nice_to_have: list[normalized_poi_spec]

    Returns:
      {
        "community": {"id","name","lat","lng",...},
        "poi_results": {category: [poi,...]},
        "must_have_satisfied": bool,
        "missing": [category,...],
        "category_scores": {category: 0..10},
        "category_counts": {top_category: total_count},
      }
    """
    lat = community.get("lat")
    lng = community.get("lng")
    if lat is None or lng is None:
        return {
            "community": community,
            "error": "missing lat/lng",
            "must_have_satisfied": False,
            "missing": [s["category"] for s in must_have],
            "poi_results": {},
        }

    all_specs = [{"_role": "must", **s} for s in must_have] + \
                [{"_role": "nice", **s} for s in nice_to_have]

    raw = parallel_map(lambda s: (s, _search_pois_for_spec(s, lat, lng)), all_specs,
                       max_workers=6)

    poi_results: dict[str, list[dict]] = {}
    must_satisfied = True
    missing: list[str] = []
    category_scores: dict[str, float] = {}
    category_counts: dict[str, int] = {}

    for item in raw:
        if not item:
            continue
        spec, pois = item
        cat = spec["category"]
        poi_results[cat] = pois
        ok = len(pois) >= spec.get("min_count", 1)
        if spec.get("_role") == "must" and not ok:
            must_satisfied = False
            missing.append(cat)
        category_scores[cat] = _score_category(spec, pois)
        top_cat = cat.split(".")[0]
        category_counts[top_cat] = category_counts.get(top_cat, 0) + len(pois)

    return {
        "community": {
            "id": community.get("id"),
            "name": community.get("name"),
            "city": community.get("city"),
            "district": community.get("district"),
            "lat": lat,
            "lng": lng,
        },
        "poi_results": poi_results,
        "must_have_satisfied": must_satisfied,
        "missing": missing,
        "category_scores": category_scores,
        "category_counts": category_counts,
    }


def _score_category(spec: dict, pois: list[dict]) -> float:
    """单类别评分（0..10）。

    满足 min_count → 满分 10
    部分满足 → 按比例
    距离越近且数量越多 → 加分
    """
    min_n = spec.get("min_count", 1)
    radius = spec.get("radius_m", 3000)
    if not pois:
        return 0.0

    # 数量分（5 分）
    count_score = min(len(pois) / max(min_n, 1), 1.0) * 5

    # 距离分（5 分）：取最近 K 个的平均距离倒数
    k = min(len(pois), 5)
    avg_dist = sum(p.get("distance_m", radius) for p in pois[:k]) / k
    dist_score = max(0.0, 5 * (1 - avg_dist / radius))

    return round(count_score + dist_score, 2)


def validate_all(communities: list[dict], must_have: list[dict],
                 nice_to_have: list[dict], max_workers: int = 5) -> list[dict]:
    """批量校验多个小区。"""
    return parallel_map(
        lambda c: validate_community(c, must_have, nice_to_have),
        communities,
        max_workers=max_workers,
        timeout=300,
    )
