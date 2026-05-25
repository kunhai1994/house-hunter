"""百度地图 API 封装（直连 REST，与 MCP 等价）。

文档：https://lbsyun.baidu.com/index.php?title=webapi
关键 API：
  - 地理编码:        https://api.map.baidu.com/geocoding/v3/
  - 逆地理编码:      https://api.map.baidu.com/reverse_geocoding/v3/
  - 地点检索-城市内:  https://api.map.baidu.com/place/v2/search?query=...&region=...
  - 地点检索-周边:    https://api.map.baidu.com/place/v2/search?query=...&location=lat,lng&radius=...
  - 地点详情:        https://api.map.baidu.com/place/v2/detail
  - 路线规划:        https://api.map.baidu.com/directionlite/v1/{driving,walking,transit,riding}
"""

from __future__ import annotations

import os
import sys
import urllib.parse
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import http_get_json, cached, haversine, RateLimiter, warn  # type: ignore


BAIDU_BASE = "https://api.map.baidu.com"
_rate = RateLimiter(min_interval_s=0.05)  # 50ms between calls (well under quota limits)

# 配额耗尽检测：连续 3 次 status=302（天配额超限）后视为今日额度已用完，
# 本会话不再尝试百度，直接让上层走高德 fallback（避免每次都白等 ~1s 才知道失败）
_QUOTA_FAIL_THRESHOLD = 3
_quota_fail_count = 0
_quota_exhausted = False


def is_quota_exhausted() -> bool:
    return _quota_exhausted


def _record_quota_fail() -> None:
    global _quota_fail_count, _quota_exhausted
    _quota_fail_count += 1
    if _quota_fail_count >= _QUOTA_FAIL_THRESHOLD:
        _quota_exhausted = True


def _record_success() -> None:
    global _quota_fail_count
    _quota_fail_count = 0


def _ak() -> str | None:
    return os.environ.get("BAIDU_MAPS_API_KEY") or os.environ.get("BAIDU_MAP_AK")


def _build(path: str, params: dict) -> str | None:
    ak = _ak()
    if not ak:
        return None
    params = {**params, "ak": ak, "output": "json"}
    return f"{BAIDU_BASE}{path}?{urllib.parse.urlencode(params)}"


@cached("baidu_geocode", ttl_seconds=86400 * 7)
def geocode(address: str, city: str | None = None) -> dict | None:
    """地址 → 经纬度。返回 {"lat": ..., "lng": ..., "confidence": int} 或 None。"""
    params = {"address": address}
    if city:
        params["city"] = city
    url = _build("/geocoding/v3/", params)
    if not url:
        return None
    _rate.wait("baidu")
    data = http_get_json(url, timeout=10)
    if not isinstance(data, dict) or data.get("status") != 0:
        return None
    loc = (data.get("result") or {}).get("location") or {}
    if "lat" not in loc or "lng" not in loc:
        return None
    return {
        "lat": loc["lat"],
        "lng": loc["lng"],
        "confidence": (data.get("result") or {}).get("confidence"),
        "level": (data.get("result") or {}).get("level"),
    }


@cached("baidu_reverse", ttl_seconds=86400 * 7)
def reverse_geocode(lat: float, lng: float) -> dict | None:
    """坐标 → 行政区/POI。"""
    url = _build("/reverse_geocoding/v3/", {
        "location": f"{lat},{lng}",
        "extensions_poi": 1,
    })
    if not url:
        return None
    _rate.wait("baidu")
    data = http_get_json(url, timeout=10)
    if not isinstance(data, dict) or data.get("status") != 0:
        return None
    return data.get("result")


@cached("baidu_search_region", ttl_seconds=86400)
def search_in_region(query: str, region: str, page_size: int = 20,
                     page_num: int = 0) -> list[dict]:
    """城市内 POI 搜索。

    Args:
      query: 关键词，如 "山姆"
      region: 城市/区，如 "深圳" 或 "深圳坪山区"
      page_size: 单页大小（百度上限 20）
      page_num: 第几页（从 0 开始）
    """
    url = _build("/place/v2/search", {
        "query": query,
        "region": region,
        "page_size": min(page_size, 20),
        "page_num": page_num,
        "scope": 2,  # 详情字段
    })
    if not url or _quota_exhausted:
        return None
    _rate.wait("baidu")
    data = http_get_json(url, timeout=12)
    if not isinstance(data, dict) or data.get("status") != 0:
        _record_quota_fail()
        return None  # API 错误（如配额超限 status=302）→ 不缓存，让上层降级
    _record_success()
    return _normalize_pois(data.get("results") or [])


@cached("baidu_search_nearby", ttl_seconds=86400)
def search_nearby(query: str, lat: float, lng: float, radius_m: int,
                  page_size: int = 20) -> list[dict]:
    """周边搜索（按 location + radius）。"""
    if _quota_exhausted:
        return None  # 配额超限快速返回，让上层走高德
    url = _build("/place/v2/search", {
        "query": query,
        "location": f"{lat},{lng}",
        "radius": radius_m,
        "page_size": min(page_size, 20),
        "scope": 2,
    })
    if not url:
        return None
    _rate.wait("baidu")
    data = http_get_json(url, timeout=12)
    if not isinstance(data, dict) or data.get("status") != 0:
        _record_quota_fail()
        return None  # API 错误（如配额超限 status=302）→ 不缓存，让上层降级
    _record_success()
    pois = _normalize_pois(data.get("results") or [])
    # 二次过滤：百度有时会越界返回，这里强制按 haversine 校验
    filtered = []
    for p in pois:
        if p.get("lat") is None or p.get("lng") is None:
            continue
        d = haversine(lat, lng, p["lat"], p["lng"])
        p["distance_m"] = round(d)
        if d <= radius_m * 1.05:  # 允许 5% 容差
            filtered.append(p)
    filtered.sort(key=lambda x: x.get("distance_m", 1e9))
    return filtered


def _normalize_pois(raw: list[dict]) -> list[dict]:
    out = []
    for r in raw:
        loc = r.get("location") or {}
        out.append({
            "uid": r.get("uid"),
            "name": r.get("name"),
            "address": r.get("address"),
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
            "telephone": r.get("telephone"),
            "city": r.get("city"),
            "area": r.get("area"),
            "tag": (r.get("detail_info") or {}).get("tag"),
            "type": (r.get("detail_info") or {}).get("type"),
            "raw_url": (r.get("detail_info") or {}).get("detail_url"),
        })
    return out


@cached("baidu_directions", ttl_seconds=3600)
def directions(origin_lat: float, origin_lng: float,
               dest_lat: float, dest_lng: float,
               mode: str = "transit") -> dict | None:
    """路线规划。mode: driving / walking / transit / riding。"""
    if mode not in {"driving", "walking", "transit", "riding"}:
        mode = "transit"
    url = _build(f"/directionlite/v1/{mode}", {
        "origin": f"{origin_lat},{origin_lng}",
        "destination": f"{dest_lat},{dest_lng}",
    })
    if not url:
        return None
    _rate.wait("baidu")
    data = http_get_json(url, timeout=15)
    if not isinstance(data, dict) or data.get("status") != 0:
        return None
    routes = (data.get("result") or {}).get("routes") or []
    if not routes:
        return None
    r = routes[0]
    return {
        "duration_s": r.get("duration"),
        "distance_m": r.get("distance"),
        "mode": mode,
    }


def health() -> bool:
    return geocode("北京") is not None
