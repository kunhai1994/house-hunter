"""Lifestyle 匹配 — 根据画像调整类别权重。

输入：lifestyle profile id 列表 + POI 校验结果
输出：每个小区的 lifestyle_score (0..100) + 加权后的 category_scores
"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import get_config  # type: ignore


def merge_weights(profile_ids: list[str]) -> dict[str, float]:
    """多个画像叠加权重（取最大值，避免叠加导致溢出）。"""
    cfg = get_config("lifestyle_profiles").get("profiles") or {}
    merged: dict[str, float] = {}
    for pid in profile_ids:
        p = cfg.get(pid)
        if not p:
            continue
        for cat, w in (p.get("category_weights") or {}).items():
            if cat not in merged or w > merged[cat]:
                merged[cat] = float(w)
    if not merged:
        # 全部 1.0
        for cat in (cfg.get("default") or {}).get("category_weights") or {}:
            merged[cat] = 1.0
    return merged


def get_extra_emphasis(profile_ids: list[str]) -> dict:
    """取所有画像的 extra_emphasis 合并（如 single_woman 的 safety 加权）。"""
    cfg = get_config("lifestyle_profiles").get("profiles") or {}
    out: dict[str, Any] = {}
    for pid in profile_ids:
        p = cfg.get(pid)
        if not p:
            continue
        emp = p.get("extra_emphasis") or {}
        for k, v in emp.items():
            if k == "safety":
                out["safety"] = max(out.get("safety", 1.0), float(v))
            elif k == "reputation_keywords":
                out.setdefault("reputation_keywords", []).extend(v)
            else:
                out[k] = v
    return out


def lifestyle_score(category_scores: dict[str, float], profile_ids: list[str]) -> dict:
    """把每个 subcategory 的 0..10 分按 lifestyle 加权聚合到 0..100。

    Args:
      category_scores: {"shopping.big_supermarket": 8.5, ...}
      profile_ids: ["nightlife", "homebody"]

    Returns:
      {
        "score": 0..100,
        "by_top_category": {"shopping": ..., "entertainment": ..., ...}
      }
    """
    weights = merge_weights(profile_ids)
    by_top: dict[str, list[float]] = {}
    for cat, sc in (category_scores or {}).items():
        top = cat.split(".")[0]
        by_top.setdefault(top, []).append(sc)

    if not by_top:
        return {"score": 0, "by_top_category": {}}

    avg_by_top: dict[str, float] = {}
    for top, scores in by_top.items():
        avg_by_top[top] = sum(scores) / len(scores)

    # 加权
    weighted_sum = 0.0
    weight_total = 0.0
    for top, avg in avg_by_top.items():
        w = weights.get(top, 1.0)
        weighted_sum += avg * w
        weight_total += w * 10  # avg 满分 10

    score = round(100 * weighted_sum / max(weight_total, 1e-9), 1) if weight_total else 0
    return {
        "score": min(score, 100),
        "by_top_category": {k: round(v, 2) for k, v in avg_by_top.items()},
    }
