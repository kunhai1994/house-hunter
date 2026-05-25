"""通勤模拟 — 计算小区到目的地的多种交通方式时间。"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sources import baidu_map, amap  # type: ignore


def simulate(origin_lat: float, origin_lng: float, dest_text: str,
             city_for_dest: str | None = None) -> dict:
    """origin 坐标 → dest（地址或地名）。

    Returns: {
      "destination": {"text", "lat", "lng"},
      "modes": {"driving": {duration_s, distance_m}, "transit": {...}, "walking": {...}}
    }
    """
    dest = baidu_map.geocode(dest_text, city_for_dest) or amap.geocode(dest_text, city_for_dest)
    if not dest:
        return {"destination": {"text": dest_text}, "error": "geocode_failed"}

    out = {
        "destination": {"text": dest_text, "lat": dest["lat"], "lng": dest["lng"]},
        "modes": {},
    }
    for mode in ("transit", "driving", "walking"):
        d = baidu_map.directions(origin_lat, origin_lng, dest["lat"], dest["lng"], mode)
        if not d:
            d = amap.directions(origin_lat, origin_lng, dest["lat"], dest["lng"], mode)
        if d:
            out["modes"][mode] = d
    return out


def commute_score(transit_duration_s: int | None, scoring_cfg: dict) -> int:
    """根据 transit 通勤时间打分 0..100。"""
    if not transit_duration_s:
        return 50
    minutes = transit_duration_s / 60
    th = scoring_cfg.get("thresholds", {})
    if minutes <= th.get("excellent", 30):
        return 100
    if minutes <= th.get("good", 45):
        return 80
    if minutes <= th.get("fair", 60):
        return 60
    if minutes <= th.get("poor", 90):
        return 30
    return 0
