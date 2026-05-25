"""口碑聚合 — 把小红书笔记按 维度（物业/噪音/邻居/快递/外卖/独居）分类，计算正负面分布。"""

from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sources import xhs  # type: ignore


# 中文关键词维度字典（轻量启发式，不依赖 NLP）
DIMENSION_KEYWORDS = {
    "物业": ["物业", "保安", "门禁", "管家", "管理处"],
    "噪音": ["噪音", "吵", "扰民", "隔音"],
    "邻居": ["邻居", "层间", "高空抛物"],
    "快递_外卖": ["快递柜", "快递", "外卖", "顺丰", "美团"],
    "独居安全": ["独居", "女生独居", "晚归", "门禁", "保安"],
    "通风采光": ["采光", "通风", "朝向", "潮湿"],
    "户型": ["户型", "格局", "动线"],
    "停车": ["停车", "车位", "车库"],
    "宠物": ["养狗", "养猫", "宠物友好"],
}

# 极性词典（轻量；不替代真正的情感分析）
POSITIVE_WORDS = ["不错", "推荐", "好", "棒", "省心", "舒服", "满意", "性价比高", "靠谱", "干净"]
NEGATIVE_WORDS = ["差", "踩雷", "坑", "避雷", "吵", "脏", "乱", "投诉", "纠纷", "破", "黑心",
                  "不推荐", "失望", "槽点"]


def aggregate(community: str, city: str = "", limit: int = 20) -> dict:
    """聚合小区口碑。

    Returns: {
      "available": bool,
      "total_notes": int,
      "by_dimension": {dim: {"positive": int, "negative": int, "notes": [feed,...]}},
      "highlights": [feed],   # 高互动正面
      "complaints": [feed],   # 高互动负面
    }
    """
    if not xhs.is_available():
        return {"available": False, "total_notes": 0, "by_dimension": {}, "highlights": [], "complaints": []}

    notes = xhs.community_reviews(community, city, limit=limit)

    by_dim: dict[str, dict] = {}
    highlights: list[dict] = []
    complaints: list[dict] = []

    for n in notes:
        text = (n.get("title") or "") + " " + (n.get("desc") or "")
        polarity = _polarity(text)
        if polarity > 0:
            highlights.append(n)
        elif polarity < 0:
            complaints.append(n)
        for dim, kws in DIMENSION_KEYWORDS.items():
            if any(k in text for k in kws):
                d = by_dim.setdefault(dim, {"positive": 0, "negative": 0, "notes": []})
                if polarity > 0:
                    d["positive"] += 1
                elif polarity < 0:
                    d["negative"] += 1
                d["notes"].append(n)

    # 按互动量排序
    highlights.sort(key=_engagement, reverse=True)
    complaints.sort(key=_engagement, reverse=True)

    return {
        "available": True,
        "total_notes": len(notes),
        "by_dimension": by_dim,
        "highlights": highlights[:8],
        "complaints": complaints[:8],
    }


def _polarity(text: str) -> int:
    pos = sum(1 for w in POSITIVE_WORDS if w in text)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text)
    if pos > neg:
        return 1
    if neg > pos:
        return -1
    return 0


def _engagement(n: dict) -> int:
    return n.get("likes", 0) + n.get("favorites", 0) * 2 + n.get("comments", 0)


def reputation_score(agg: dict, scoring_cfg: dict) -> dict:
    """根据正负比 + 总笔记数计算 0..100。"""
    if not agg.get("available") or agg.get("total_notes", 0) < scoring_cfg.get("min_notes_for_score", 5):
        return {"score": 50, "note": "笔记数不足，置为中性"}

    pos_w = scoring_cfg.get("positive_review_weight", 1.0)
    neg_w = abs(scoring_cfg.get("negative_review_weight", -1.5))

    pos_total = sum(d.get("positive", 0) for d in agg["by_dimension"].values())
    neg_total = sum(d.get("negative", 0) for d in agg["by_dimension"].values())
    total = max(pos_total + neg_total, 1)

    raw = (pos_total * pos_w - neg_total * neg_w) / total
    # 把 -neg_w..+pos_w 映射到 0..100
    span = pos_w + neg_w
    score = round(((raw + neg_w) / span) * 100)
    return {
        "score": max(0, min(100, score)),
        "positive_count": pos_total,
        "negative_count": neg_total,
    }
