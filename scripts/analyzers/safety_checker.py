"""安全风险扫描 — 多关键词并行检索 xhs + Bing 新闻。"""

from __future__ import annotations

import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import get_config, parallel_map  # type: ignore
from sources import xhs, news_search  # type: ignore


def all_keywords_with_severity(lite: bool = True) -> list[tuple[str, str]]:
    """返回 [(keyword, severity), ...]。

    lite=True (默认)：每个类别取前 2 个最具代表性的关键词，控制 xhs 调用量
    lite=False：全部返回（thorough 模式，xhs 调用量大约 4 倍）
    """
    cfg = get_config("safety_keywords")
    out: list[tuple[str, str]] = []
    for cat_data in (cfg.get("categories") or {}).values():
        sev = cat_data.get("severity", "low")
        kws = cat_data.get("keywords") or []
        if lite:
            kws = kws[:2]  # 每个类别只取前 2 个
        for kw in kws:
            out.append((kw, sev))
    return out


def check_community(community: str, city: str = "", thorough: bool = False) -> dict:
    """对单小区执行安全检查。

    Args:
      community: 小区名
      city: 城市
      thorough: True = 用全部 51 个关键词（慢，给报告生成器用），
                False = lite 模式（每类前 2 个，约 16 个关键词；e2e 默认）

    Returns: {
      "incidents": [
        {"keyword","severity","title","url","source","snippet","date"?}
      ],
      "by_severity": {"high": int, "medium": int, "low": int},
      "summary": str
    }
    """
    kws = all_keywords_with_severity(lite=not thorough)
    keywords = [kw for kw, _ in kws]
    sev_map = dict(kws)

    # 小红书检索（如果可用）
    xhs_findings: list[dict] = []
    if xhs.is_available():
        xhs_results = xhs.safety_search(community, city, risk_keywords=keywords, limit=30)
        for r in xhs_results:
            text = r.get("title", "") + " " + r.get("desc", "")
            # ⚠️ 关键改动：必须同时含 risk keyword + 小区名（或别名），
            #             否则就是 false positive（如「自杀心理学」纯关键词命中但跟小区无关）
            if not _mentions_community(text, community):
                continue
            matched_kw, sev = _match_keyword(text, kws)
            if not matched_kw:
                continue
            xhs_findings.append({
                "keyword": matched_kw,
                "severity": sev,
                "title": r.get("title"),
                "url": r.get("url"),
                "source": "xiaohongshu",
                "snippet": (r.get("desc") or "")[:160],
                "engagement": (r.get("likes", 0) + r.get("favorites", 0) +
                               r.get("comments", 0)),
            })

    # Bing 新闻检索
    news_findings: list[dict] = []
    news_results = news_search.safety_incidents(community, city, keywords=keywords)
    for r in news_results:
        text = (r.get("title") or "") + " " + (r.get("snippet") or "")
        # 同 xhs：news 也要求标题/摘要含小区名
        if not _mentions_community(text, community):
            continue
        matched_kw = r.get("keyword") or ""
        sev = sev_map.get(matched_kw, "low")
        news_findings.append({
            "keyword": matched_kw,
            "severity": sev,
            "title": r.get("title"),
            "url": r.get("url"),
            "source": r.get("engine") or "news",
            "snippet": r.get("snippet", ""),
        })

    incidents = _dedupe(xhs_findings + news_findings)
    by_sev = {"high": 0, "medium": 0, "low": 0}
    for i in incidents:
        s = i.get("severity") or "low"
        if s in by_sev:
            by_sev[s] += 1

    return {
        "community": community,
        "city": city,
        "incidents": incidents,
        "by_severity": by_sev,
        "summary": _summarize(by_sev, len(incidents)),
        "xhs_available": xhs.is_available(),
    }


def _mentions_community(text: str, community: str) -> bool:
    """文本里是否真的提到了目标小区。

    支持几种变体：
    - 完整名称：「滨水花园」
    - 去除常见后缀：「滨水」（去掉「花园/小区/苑/城」等）
    - 全角/半角空格容忍

    注：不要太宽松，否则会把不相关帖子（如「滨水公园」）也误判进来。
    """
    if not text or not community:
        return False
    if community in text:
        return True
    # 去掉常见后缀的简称
    short = community
    for suffix in ("花园", "小区", "公寓", "苑", "城", "庭", "府", "湾", "邸", "园"):
        if short.endswith(suffix) and len(short) > len(suffix) + 1:
            short = short[: -len(suffix)]
            break
    # 简称必须 ≥3 个字符才用（避免「街」「号」之类太短的误判）
    if len(short) >= 3 and short != community and short in text:
        return True
    return False


def _match_keyword(text: str, kws: list[tuple[str, str]]) -> tuple[str | None, str]:
    """在 text 中匹配第一个 keyword，返回 (kw, severity)。优先 high → low。"""
    sev_priority = {"high": 0, "medium": 1, "low": 2}
    sorted_kws = sorted(kws, key=lambda x: sev_priority.get(x[1], 3))
    for kw, sev in sorted_kws:
        if kw and kw in text:
            return kw, sev
    return None, "low"


def _dedupe(items: list[dict]) -> list[dict]:
    """按 url 或 (title 前 30 字) 去重。"""
    seen: dict[str, dict] = {}
    for it in items:
        key = it.get("url") or (it.get("title") or "")[:30]
        if not key or key in seen:
            continue
        seen[key] = it
    # 按 severity（high 先）+ engagement 排序
    sev_priority = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        seen.values(),
        key=lambda x: (sev_priority.get(x.get("severity"), 3),
                       -x.get("engagement", 0)),
    )


def _summarize(by_sev: dict, total: int) -> str:
    if total == 0:
        return "未查到风险事件（注意：未查到不代表没有发生）"
    parts = []
    if by_sev["high"]:
        parts.append(f"⚠️ 高严重 {by_sev['high']} 条")
    if by_sev["medium"]:
        parts.append(f"中等 {by_sev['medium']} 条")
    if by_sev["low"]:
        parts.append(f"轻微 {by_sev['low']} 条")
    return "；".join(parts) if parts else "无明显风险"


def safety_score(by_sev: dict, scoring_cfg: dict) -> int:
    """根据 by_severity 算 0..100。"""
    score = 100
    score -= by_sev.get("high", 0) * scoring_cfg.get("high_severity_penalty", 30)
    score -= by_sev.get("medium", 0) * scoring_cfg.get("medium_severity_penalty", 12)
    score -= by_sev.get("low", 0) * scoring_cfg.get("low_severity_penalty", 4)

    if score == 100:
        # 没查到 ≠ 没发生
        score = scoring_cfg.get("no_findings_floor", 80)

    return max(0, min(100, score))
