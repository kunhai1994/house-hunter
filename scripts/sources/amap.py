"""高德地图 API 封装（备用源，与 baidu_map 接口对齐）。

文档：https://lbs.amap.com/api/webservice
"""

from __future__ import annotations

import os
import sys
import urllib.parse
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import http_get_json, cached, haversine, RateLimiter  # type: ignore


AMAP_BASE = "https://restapi.amap.com/v3"
_rate = RateLimiter(min_interval_s=0.05)

# 配额耗尽检测（与 baidu_map 对称）：连续 N 次失败后熔断
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


def _key() -> str | None:
    return os.environ.get("AMAP_MAPS_API_KEY") or os.environ.get("AMAP_KEY")


def _build(path: str, params: dict) -> str | None:
    k = _key()
    if not k:
        return None
    params = {**params, "key": k, "output": "json"}
    return f"{AMAP_BASE}{path}?{urllib.parse.urlencode(params)}"


@cached("amap_geocode", ttl_seconds=86400 * 7)
def geocode(address: str, city: str | None = None) -> dict | None:
    params = {"address": address}
    if city:
        params["city"] = city
    url = _build("/geocode/geo", params)
    if not url:
        return None
    _rate.wait("amap")
    data = http_get_json(url, timeout=10)
    if not isinstance(data, dict) or str(data.get("status")) != "1":
        return None
    geocodes = data.get("geocodes") or []
    if not geocodes:
        return None
    g = geocodes[0]
    loc = (g.get("location") or "").split(",")
    if len(loc) != 2:
        return None
    try:
        lng, lat = float(loc[0]), float(loc[1])
    except ValueError:
        return None
    return {"lat": lat, "lng": lng, "level": g.get("level"), "adcode": g.get("adcode")}


@cached("amap_reverse", ttl_seconds=86400 * 7)
def reverse_geocode(lat: float, lng: float) -> dict | None:
    url = _build("/geocode/regeo", {
        "location": f"{lng},{lat}",
        "extensions": "all",
    })
    if not url:
        return None
    _rate.wait("amap")
    data = http_get_json(url, timeout=10)
    if not isinstance(data, dict) or str(data.get("status")) != "1":
        return None
    return data.get("regeocode")


@cached("amap_search_region", ttl_seconds=86400)
def search_in_region(query: str, region: str, page_size: int = 25,
                     page_num: int = 1) -> list[dict]:
    if _quota_exhausted:
        return None
    url = _build("/place/text", {
        "keywords": query,
        "city": region,
        "citylimit": "true",
        "offset": min(page_size, 25),
        "page": max(page_num, 1),
    })
    if not url:
        return None
    _rate.wait("amap")
    data = http_get_json(url, timeout=12)
    if not isinstance(data, dict) or str(data.get("status")) != "1":
        _record_quota_fail()
        return None  # API 错误（配额/网络）→ 不缓存
    _record_success()
    return _normalize_pois(data.get("pois") or [])


@cached("amap_search_nearby", ttl_seconds=86400)
def search_nearby(query: str, lat: float, lng: float, radius_m: int,
                  page_size: int = 25) -> list[dict]:
    if _quota_exhausted:
        return None
    url = _build("/place/around", {
        "keywords": query,
        "location": f"{lng},{lat}",  # amap is lng,lat
        "radius": radius_m,
        "offset": min(page_size, 25),
        "extensions": "base",
    })
    if not url:
        return None
    _rate.wait("amap")
    data = http_get_json(url, timeout=12)
    if not isinstance(data, dict) or str(data.get("status")) != "1":
        _record_quota_fail()
        return None  # API 错误（配额/网络）→ 不缓存
    _record_success()
    pois = _normalize_pois(data.get("pois") or [])
    out = []
    for p in pois:
        if p.get("lat") is None or p.get("lng") is None:
            continue
        d = haversine(lat, lng, p["lat"], p["lng"])
        p["distance_m"] = round(d)
        if d <= radius_m * 1.05:
            out.append(p)
    out.sort(key=lambda x: x.get("distance_m", 1e9))
    return out


def _normalize_pois(raw: list[dict]) -> list[dict]:
    out = []
    for r in raw:
        loc = (r.get("location") or "").split(",")
        if len(loc) == 2:
            try:
                lng, lat = float(loc[0]), float(loc[1])
            except ValueError:
                lat, lng = None, None
        else:
            lat, lng = None, None
        out.append({
            "uid": r.get("id"),
            "name": r.get("name"),
            "address": r.get("address"),
            "lat": lat,
            "lng": lng,
            "telephone": r.get("tel"),
            "city": r.get("cityname"),
            "area": r.get("adname"),
            "tag": r.get("tag"),
            "type": r.get("type"),
        })
    return out


@cached("amap_directions", ttl_seconds=3600)
def directions(origin_lat: float, origin_lng: float,
               dest_lat: float, dest_lng: float,
               mode: str = "transit") -> dict | None:
    """路线规划。mode: driving / walking / transit / riding。"""
    path_map = {
        "driving": "/direction/driving",
        "walking": "/direction/walking",
        "riding": "/direction/bicycling",
        "transit": "/direction/transit/integrated",
    }
    path = path_map.get(mode, "/direction/transit/integrated")
    params = {
        "origin": f"{origin_lng},{origin_lat}",
        "destination": f"{dest_lng},{dest_lat}",
    }
    if mode == "transit":
        params["city"] = "010"  # 起点城市占位，实际 API 用 reverse_geocode 推导更稳，但这里走兜底
    url = _build(path, params)
    if not url:
        return None
    _rate.wait("amap")
    data = http_get_json(url, timeout=15)
    if not isinstance(data, dict) or str(data.get("status")) != "1":
        return None
    route = data.get("route") or {}
    paths = route.get("paths") or route.get("transits") or []
    if not paths:
        return None
    p = paths[0]
    return {
        "duration_s": int(p.get("duration", 0)) if p.get("duration") else None,
        "distance_m": int(p.get("distance", 0)) if p.get("distance") else None,
        "mode": mode,
    }


def health() -> bool:
    return geocode("北京") is not None
