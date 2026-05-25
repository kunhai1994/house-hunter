"""综合评分 — 把各维度分数按权重聚合。"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import get_config  # type: ignore
from analyzers.lifestyle_matcher import (  # type: ignore
    lifestyle_score, get_extra_emphasis,
)
from analyzers.rental_analyzer import rental_score  # type: ignore
from analyzers.safety_checker import safety_score  # type: ignore
from analyzers.sentiment_aggregator import reputation_score  # type: ignore
from analyzers.commute_simulator import commute_score  # type: ignore


def score(community: dict, poi_validation: dict, rental_info: dict,
          sentiment: dict, safety: dict, commute: dict | None,
          requirement: dict) -> dict:
    """综合评分。

    Returns: {
      "total": 0..100,
      "components": {"poi": ..., "rental": ..., "reputation": ..., "safety": ..., "commute": ...},
      "weights": {...},
      "missing_must_have": [...],
    }
    """
    cfg = get_config("scoring")
    weights = dict(cfg.get("weights") or {})

    # POI 评分（含 lifestyle 加权）
    profiles = requirement.get("lifestyle_profile") or ["default"]
    poi_score = lifestyle_score(poi_validation.get("category_scores") or {}, profiles)

    # 必备项缺失惩罚
    missing = poi_validation.get("missing") or []
    poi_value = poi_score["score"]
    if missing:
        penalty = (cfg.get("poi_match") or {}).get("must_have_unsatisfied_penalty", 30)
        poi_value = max(0, poi_value - penalty * len(missing))

    # 租金
    target_room = requirement.get("rooms")
    budget = (requirement.get("budget") or {}).get("max_per_month")
    rent_eval = rental_score(rental_info, target_room, budget)
    rent_value = rent_eval.get("score", 50)

    # 口碑
    rep_eval = reputation_score(sentiment or {}, cfg.get("reputation") or {})
    rep_value = rep_eval.get("score", 50)

    # 安全
    safety_value = safety_score(
        safety.get("by_severity") or {"high": 0, "medium": 0, "low": 0},
        cfg.get("safety") or {},
    )

    # 通勤
    commute_value = None
    if commute and commute.get("modes", {}).get("transit"):
        commute_value = commute_score(
            commute["modes"]["transit"].get("duration_s"),
            cfg.get("commute") or {},
        )

    # 权重调整：未启用通勤时把权重匀给 poi
    if commute_value is None:
        weights["poi_match"] = weights.get("poi_match", 40) + weights.pop("commute", 5)
        commute_value = 0

    # 安全 lifestyle 加权（如 single_woman）
    extra = get_extra_emphasis(profiles)
    safety_weight_mult = float(extra.get("safety", 1.0))
    if safety_weight_mult != 1.0:
        # 把 safety 权重提高一点（不超过 +30%）
        delta = min(weights.get("safety", 15) * (safety_weight_mult - 1), 8)
        weights["safety"] = weights.get("safety", 15) + delta
        weights["poi_match"] = max(weights.get("poi_match", 40) - delta, 10)

    components = {
        "poi": round(poi_value, 1),
        "rental": round(rent_value, 1),
        "reputation": round(rep_value, 1),
        "safety": round(safety_value, 1),
        "commute": round(commute_value or 0, 1),
    }

    # 加权聚合
    w_total = sum(weights.values())
    total = (
        components["poi"] * weights.get("poi_match", 40)
        + components["rental"] * weights.get("rental", 20)
        + components["reputation"] * weights.get("reputation", 20)
        + components["safety"] * weights.get("safety", 15)
        + components["commute"] * weights.get("commute", 0)
    ) / max(w_total, 1)

    return {
        "total": round(total, 1),
        "components": components,
        "weights": weights,
        "missing_must_have": missing,
        "rental_note": rent_eval.get("note"),
        "lifestyle_breakdown": poi_score.get("by_top_category"),
    }
