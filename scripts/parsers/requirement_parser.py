"""需求解析 — 把 LLM 解析后的 JSON 校验/补全。

主路径：LLM 在 SKILL.md 阶段把自然语言解析为 JSON，传给 engine。
本模块负责：
  1. 校验 JSON schema
  2. 补充默认值（POI 半径默认值、lifestyle 默认权重）
  3. 标准化 city/district
  4. 展开 POI 类别为搜索关键词
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import get_config  # type: ignore
from parsers.city_resolver import normalize, resolve  # type: ignore


# ---------------------------------------------------------------------------
# Lifestyle 触发词识别（LLM 没识别时的兜底）
# ---------------------------------------------------------------------------
def detect_lifestyle_profiles(text: str) -> list[str]:
    """从原始文本中识别 lifestyle profile id 列表。"""
    if not text:
        return ["default"]
    profiles = get_config("lifestyle_profiles").get("profiles") or {}
    matched = []
    for pid, p in profiles.items():
        if pid == "default":
            continue
        triggers = p.get("triggers") or []
        for t in triggers:
            if t and t in text:
                matched.append(pid)
                break
    return matched or ["default"]


# ---------------------------------------------------------------------------
# POI 类别校验 + 关键词展开
# ---------------------------------------------------------------------------
def expand_poi_category(cat: str) -> dict | None:
    """'shopping.big_supermarket' → {label, primary_keywords, brand_keywords, ...}。

    向后兼容：旧 yaml 用 keywords 字段（无 primary/brand 区分），仍然可读。
    """
    if "." not in cat:
        return None
    top, sub = cat.split(".", 1)
    cfg = get_config("poi_categories")
    sub_cfg = ((cfg.get(top) or {}).get("subcategories") or {}).get(sub)
    if not sub_cfg:
        return None

    # 优先用新格式 (primary_keywords + brand_keywords)，回退到旧 keywords 字段
    primary = list(sub_cfg.get("primary_keywords") or [])
    brand = list(sub_cfg.get("brand_keywords") or [])
    legacy = list(sub_cfg.get("keywords") or [])
    if not primary and legacy:
        # 旧格式回退：所有 legacy keywords 当作 primary（行为同 v1）
        primary = legacy
    return {
        "category": cat,
        "label": sub_cfg.get("label", cat),
        "primary_keywords": primary,
        "brand_keywords": brand,
        "expected_tags": list(sub_cfg.get("expected_tags") or []),
        "default_radius_m": sub_cfg.get("default_radius_m", 3000),
    }


def normalize_poi_spec(spec: dict) -> dict:
    """统一 must_have_pois / nice_to_have_pois 内单条的格式。

    新版 schema：
      - search_keywords: 用来调 API 的（少而泛）
      - brand_keywords:  用来识别 / 显示品牌（不调 API）
      - expected_tags:   POI tag/type 强校验
      - must_have_brand: 用户显式要求的品牌（用于 brand_keywords 子集过滤）

    向后兼容：用户传入的 match_keywords（v1）会作为 search_keywords。
    """
    cat = spec.get("category")
    expanded = expand_poi_category(cat) if cat else None

    # search_keywords 优先级：用户 match_keywords > yaml primary > yaml legacy keywords
    search_kws = list(spec.get("match_keywords") or [])
    if not search_kws and expanded:
        search_kws = list(expanded.get("primary_keywords") or [])

    brand_kws = list(spec.get("brand_keywords") or [])
    if not brand_kws and expanded:
        brand_kws = list(expanded.get("brand_keywords") or [])

    out = {
        "category": cat,
        "label": expanded["label"] if expanded else cat,
        "search_keywords": search_kws,        # 调 API 用
        "brand_keywords": brand_kws,          # 显示品牌 / 过滤 must_have_brand 用
        "keywords": search_kws,               # 向后兼容（旧代码读 keywords）
        "expected_tags": list(spec.get("expected_tags") or (expanded["expected_tags"] if expanded else [])),
        "min_count": int(spec.get("min_count", 1)),
        "radius_m": int(spec.get("radius_m") or (expanded["default_radius_m"] if expanded else 3000)),
        "must_have_brand": list(spec.get("must_have_brand") or []),
    }
    return out


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def validate_and_normalize(req: dict) -> dict:
    """校验+补全 requirement。失败时 raise。"""
    if not isinstance(req, dict):
        raise ValueError("requirement 必须是 dict")

    intent = req.get("intent") or "search"
    if intent not in {"search", "research"}:
        raise ValueError(f"intent 非法: {intent}")

    raw = req.get("raw") or ""

    # City / district 标准化
    city = req.get("city")
    district = req.get("district")
    area = req.get("area")
    if not city and raw:
        loc = resolve(raw)
        if loc:
            city = loc["city"]
            district = district or loc.get("district")
            area = area or loc.get("area")
    norm = normalize(city, district)
    city = norm["city"] or city
    district = norm["district"] or district
    area = norm["area"] or area

    if not city:
        raise ValueError(f"无法识别城市；请在 raw 或 city 字段提供（raw={raw!r}）")

    # Lifestyle
    profiles = req.get("lifestyle_profile") or []
    if not profiles:
        profiles = detect_lifestyle_profiles(raw)
    valid_profiles = (get_config("lifestyle_profiles").get("profiles") or {}).keys()
    profiles = [p for p in profiles if p in valid_profiles] or ["default"]

    # POI 规格规范化
    must_have = [normalize_poi_spec(s) for s in (req.get("must_have_pois") or [])]
    nice = [normalize_poi_spec(s) for s in (req.get("nice_to_have_pois") or [])]

    # 默认 top_n
    if intent == "search":
        top_n = int(req.get("top_n") or 5)
    else:
        top_n = int(req.get("top_n") or 8)

    out = {
        "intent": intent,
        "city": city,
        "district": district,
        "area": area,
        "search_radius_m": req.get("search_radius_m"),  # 中心点搜索半径 (m)，仅 area 非空时生效；默认 1000
        "rooms": req.get("rooms"),
        "halls": req.get("halls"),
        "area_min_sqm": req.get("area_min_sqm"),
        "area_max_sqm": req.get("area_max_sqm"),
        "budget": req.get("budget") or {},
        "lifestyle_profile": profiles,
        "must_have_pois": must_have,
        "nice_to_have_pois": nice,
        "commute_destination": req.get("commute_destination"),
        "top_n": top_n,
        "raw": raw,
    }
    return out


# CLI for testing
if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            req = json.load(f)
    else:
        req = json.loads(sys.stdin.read())
    out = validate_and_normalize(req)
    print(json.dumps(out, ensure_ascii=False, indent=2))
