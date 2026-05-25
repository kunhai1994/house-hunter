"""租金分析 — 整合 sources/rental 的多源数据，输出可用于报告的结构化结果。"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sources import rental  # type: ignore


def analyze_community(community_id: str, city: str) -> dict:
    """单小区租金分析。

    返回：{
      "community_id", "url",
      "by_room": {"one_bedroom": {...}, "two_bedroom": {...}, "three_bedroom": {...}, "shared_room": {...}},
      "total_listings": int,
      "available": bool
    }
    """
    summary = rental.community_rental_summary(community_id, city)
    if not summary:
        return {"community_id": community_id, "available": False}

    return {
        "community_id": community_id,
        "url": summary.get("url"),
        "by_room": {
            "one_bedroom": summary.get("one_bedroom"),
            "two_bedroom": summary.get("two_bedroom"),
            "three_bedroom": summary.get("three_bedroom"),
            "shared_room": summary.get("shared_room"),
        },
        "total_listings": summary.get("total_listings", 0),
        "available": summary.get("total_listings", 0) > 0,
    }


def rental_score(rental_info: dict, target_room: int | None,
                 budget_max: int | None) -> dict:
    """根据预算 + 户型计算租金合理性 0..100。"""
    if not rental_info or not rental_info.get("available"):
        return {"score": 50, "note": "无租金数据，置为中性"}

    room_key = {1: "one_bedroom", 2: "two_bedroom", 3: "three_bedroom"}.get(target_room or 0)
    if not room_key:
        # 默认看两房
        room_key = "two_bedroom"

    room_data = (rental_info.get("by_room") or {}).get(room_key) or {}
    avg = room_data.get("avg")
    if not avg:
        # 无对应户型，找最接近的
        for k in ["two_bedroom", "one_bedroom", "three_bedroom", "shared_room"]:
            d = (rental_info.get("by_room") or {}).get(k) or {}
            if d.get("avg"):
                avg = d["avg"]
                room_key = k
                break

    if not avg:
        return {"score": 50, "note": "本户型无挂牌"}

    if not budget_max or budget_max <= 0:
        # 无预算限制 → 仅基于挂牌量打分
        listings = rental_info.get("total_listings", 0)
        return {
            "score": min(100, 60 + listings),
            "avg_rent": avg,
            "matched_room": room_key,
        }

    over = avg - budget_max
    if over <= 0:
        score = 100
        note = "在预算内"
    elif over <= budget_max * 0.10:
        score = 80
        note = f"超预算 {over} 元（≤10%）"
    elif over <= budget_max * 0.20:
        score = 50
        note = f"超预算 {over} 元（10-20%）"
    else:
        score = 20
        note = f"超预算 {over} 元（>20%）"

    return {
        "score": score,
        "avg_rent": avg,
        "budget_max": budget_max,
        "matched_room": room_key,
        "note": note,
    }
