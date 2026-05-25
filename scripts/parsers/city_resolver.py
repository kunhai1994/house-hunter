"""城市/区域名标准化。

不依赖 LLM 的快速规则匹配；LLM 的解析结果也会经过这一层校准。
"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import get_config  # type: ignore


def resolve(text: str) -> dict | None:
    """从片段文本中识别 city/district/area。

    设计原则：
      - **不做城市白名单限制** — 中国大陆任意城市/县级市都可用
      - city_aliases.yaml 仅作输入便利层（如「坪山」自动补 city=深圳市）
      - 命中字典 → 返回结构化结果；未命中 → 返回 None（调用方走百度地图地理编码兜底）

    返回 {"city": str, "district": str|None, "area": str|None}，未识别返回 None。
    """
    if not text:
        return None
    cfg = get_config("city_aliases")
    cities = cfg.get("cities") or {}
    districts = cfg.get("districts") or {}

    out: dict[str, Any] = {"city": None, "district": None, "area": None}

    # district 优先（更具体），命中后顺带带出 city
    for k in sorted(districts.keys(), key=len, reverse=True):
        if k and k in text:
            d = districts[k]
            out["city"] = d.get("city")
            out["district"] = d.get("district")
            if d.get("area"):
                out["area"] = d["area"]
            break

    # 城市字典扫描（仅做别名补全）
    if not out["city"]:
        for k in sorted(cities.keys(), key=len, reverse=True):
            if k and k in text:
                out["city"] = cities[k]
                break

    return out if out["city"] else None


def normalize(city: str | None, district: str | None = None) -> dict:
    """直接给定 city/district，做规范化。

    设计原则：
      - **不做白名单限制** — 任意城市名直接通过
      - 字典命中时做别名补全（"坪山" → "深圳市/坪山区"）
      - 字典未命中时按用户输入原样返回，并自动补「市」字以适配地图 API
    """
    out = {"city": None, "district": None, "area": None}
    cfg = get_config("city_aliases")
    cities = cfg.get("cities") or {}
    districts = cfg.get("districts") or {}

    if city:
        # 先看是不是城市名
        if city in cities:
            out["city"] = cities[city]
        elif city in districts:
            # 用户把 district 当 city 写了
            d = districts[city]
            out["city"] = d.get("city")
            out["district"] = out["district"] or d.get("district")
            if d.get("area"):
                out["area"] = d["area"]
        else:
            # **未命中字典 — 不限制**，原样保留，自动补「市」
            normalized = city
            if not normalized.endswith(("市", "县", "州", "盟", "区", "省")) and len(normalized) <= 6:
                normalized = normalized + "市"
            out["city"] = normalized

    if district:
        d = districts.get(district)
        if d:
            out["city"] = out["city"] or d.get("city")
            out["district"] = d.get("district")
            if d.get("area"):
                out["area"] = d["area"]
        else:
            out["district"] = district
    return out


def validate_via_geocoding(city: str) -> dict | None:
    """用地图 API 校验任意城市名（用于白名单外的城市）。

    Returns: {"city": str, "lat": float, "lng": float, "adcode": str|None} 或 None
    """
    # 延迟导入，避免循环
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from sources import baidu_map, amap  # type: ignore

    geo = baidu_map.geocode(city) or amap.geocode(city)
    if not geo:
        return None
    return {
        "city": city,
        "lat": geo.get("lat"),
        "lng": geo.get("lng"),
        "adcode": geo.get("adcode"),
    }
