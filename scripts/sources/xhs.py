"""小红书数据源 — 通过 subprocess 调用 xiaohongshu-skills 的 cli.py。

架构：cli.py + bridge_server + Chrome Extension，借用户已登录的浏览器抓取
（真账号真浏览器 → 反爬指纹强；不会自启 Chrome 不爆内存）。

cli.py 出口：
  exit 0 = 成功
  exit 1 = 未登录（→ 熔断）
  exit 2 = 其他错误
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import threading
import time as _time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import (  # type: ignore
    cached, parallel_map,
    find_xhs_skills_root, check_xhs_skills_available,
)


# ---------------------------------------------------------------------------
# 全局并发限制 + 反爬防护（深度防御）
#
# 背景：用户的小红书账号被风控警告过一次（2026-05 测试期间，xhs-mcp 高并发引起）。
# 即使切到 xhs-skills 用真浏览器，仍要保守：
#   1. Semaphore(1) — 同一时刻只跑 1 个 search，不并发
#   2. 每次 search 之间 2-8s 随机 jitter — 模拟人行为
#   3. 探针失败可熔断
# ---------------------------------------------------------------------------
_xhs_global_semaphore = threading.Semaphore(1)  # 同一时刻最多 1 个 xhs 请求
_xhs_circuit_broken = False                      # 熔断后本会话不再发请求

# 反爬节流：每次 search 之间至少间隔的随机秒数
_HUMAN_LIKE_INTERVAL_MIN_S = 2.0
_HUMAN_LIKE_INTERVAL_MAX_S = 8.0
_last_search_at: float = 0.0
_jitter_lock = threading.Lock()


def is_available() -> bool:
    global _xhs_circuit_broken
    if _xhs_circuit_broken:
        return False
    # 手动开关：HOUSE_HUNTER_DISABLE_XHS=1 → 跳过 xhs（账号风控冷却用）
    if os.environ.get("HOUSE_HUNTER_DISABLE_XHS"):
        return False
    return check_xhs_skills_available()


def trip_circuit_breaker(reason: str = "") -> None:
    """探针失败 / 用户紧急刹车后调用。本进程内不再发 xhs 请求。"""
    global _xhs_circuit_broken
    _xhs_circuit_broken = True


def _human_like_pause() -> None:
    """两次 search 之间至少间隔 2-8s 随机 jitter。距上次 >30s 时不再额外 sleep。"""
    global _last_search_at
    with _jitter_lock:
        elapsed = _time.time() - _last_search_at
        if _last_search_at > 0 and elapsed < 30:
            target = random.uniform(_HUMAN_LIKE_INTERVAL_MIN_S, _HUMAN_LIKE_INTERVAL_MAX_S)
            wait = max(0.0, target - elapsed)
            if wait > 0:
                _time.sleep(wait)
        _last_search_at = _time.time()


# ---------------------------------------------------------------------------
# subprocess 调用 cli.py
# ---------------------------------------------------------------------------
def _run_cli(*args: str, timeout: int = 60) -> dict | None:
    """运行 xhs-skills 的 cli.py 子命令，返回 JSON dict。

    失败返 None。exit 1（未登录）会自动熔断。
    """
    root = find_xhs_skills_root()
    if not root:
        return None

    cli = os.path.join(root, "scripts", "cli.py")
    cmd = [sys.executable, cli, *args]

    try:
        result = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None

    # 未登录 → 熔断
    if result.returncode == 1:
        trip_circuit_breaker("xhs-skills returned exit 1 (not logged in)")
        return None

    if result.returncode != 0:
        return None

    try:
        return json.loads(result.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# 底层 search / detail（带缓存 + 节流 + 熔断）
# ---------------------------------------------------------------------------
@cached("xhs_search", ttl_seconds=21600)  # 6h
def search_feeds(keyword: str, max_results: int = 30) -> list[dict]:
    """搜索小红书笔记。返回归一化的 list[dict]。"""
    if _xhs_circuit_broken:
        return []
    if not _xhs_global_semaphore.acquire(timeout=120):
        return []
    try:
        _human_like_pause()
        # cli.py search-feeds 大约 ~10s，给 60s 缓冲
        data = _run_cli("search-feeds", "--keyword", keyword, timeout=60)
    finally:
        _xhs_global_semaphore.release()

    if not isinstance(data, dict):
        return []
    feeds = data.get("feeds") or []
    return _normalize_feeds(feeds[:max_results])


@cached("xhs_detail", ttl_seconds=21600)
def feed_detail(feed_id: str, xsec_token: str | None = None) -> dict | None:
    """获取笔记完整正文 + 评论。"""
    if _xhs_circuit_broken:
        return None
    if not feed_id or not xsec_token:
        return None
    if not _xhs_global_semaphore.acquire(timeout=120):
        return None
    try:
        _human_like_pause()
        data = _run_cli(
            "get-feed-detail",
            "--feed-id", feed_id,
            "--xsec-token", xsec_token,
            timeout=60,
        )
    finally:
        _xhs_global_semaphore.release()
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# 归一化 cli.py 的输出（扁平格式，比 mcp 简单）
# ---------------------------------------------------------------------------
def _normalize_feeds(raw: list[dict]) -> list[dict]:
    """xhs-skills cli.py search-feeds 输出 schema：
      {
        "id": "...",
        "xsecToken": "...",
        "modelType": "note",
        "displayTitle": "...",
        "type": "video|normal",
        "user": {"userId": "...", "nickname": "..."},
        "interactInfo": {
            "likedCount": "121",
            "collectedCount": "106",
            "commentCount": "332",
            "sharedCount": ""
        },
        "cover": "https://...",
        "video": {"duration": 23}  // 仅视频
      }
    """
    out = []
    for r in raw:
        feed_id = r.get("id") or r.get("feed_id")
        user = r.get("user") or {}
        ii = r.get("interactInfo") or r.get("interact_info") or {}
        out.append({
            "feed_id": feed_id,
            "title": r.get("displayTitle") or r.get("display_title") or r.get("title") or "",
            "desc": r.get("desc") or "",
            "url": _build_url(feed_id),
            "author": user.get("nickname") or user.get("nickName"),
            "author_id": user.get("userId"),
            "likes": _to_int(ii.get("likedCount") or ii.get("liked_count")),
            "favorites": _to_int(ii.get("collectedCount") or ii.get("collected_count")),
            "comments": _to_int(ii.get("commentCount") or ii.get("comment_count")),
            "shares": _to_int(ii.get("sharedCount") or ii.get("shared_count")),
            "type": r.get("type"),
            "cover": r.get("cover"),
            "xsec_token": r.get("xsecToken") or r.get("xsec_token"),
        })
    return out


def _to_int(v) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(v)
    except (ValueError, TypeError):
        s = str(v).replace(",", "").strip()
        if s.endswith("万"):
            try:
                return int(float(s[:-1]) * 10000)
            except ValueError:
                return 0
        try:
            return int(float(s))
        except ValueError:
            return 0


def _build_url(feed_id: str | None) -> str | None:
    if not feed_id:
        return None
    return f"https://www.xiaohongshu.com/explore/{feed_id}"


# ---------------------------------------------------------------------------
# 高层 API（面向年轻租客找房，跟 v1 完全兼容）
# ---------------------------------------------------------------------------
def community_reviews(community: str, city: str = "", limit: int = 20) -> list[dict]:
    """小区住户口碑。多关键词搜索 + 去重。

    注：跟旧版相比，因为反爬考虑只用 2 个关键词（不是 4 个），减少调用量。
    """
    keywords = [
        f"{community}",
        f"{community} 居住体验",
    ]
    if city:
        keywords = [f"{city} {kw}" for kw in keywords]
    return _multi_search_dedupe(keywords, per_keyword=15, total_limit=limit)


def district_vibe(district: str, city: str, limit: int = 15) -> list[dict]:
    """区域氛围、年轻人评价。"""
    keywords = [
        f"{city} {district} 租房",
        f"{city} {district} 年轻人",
    ]
    return _multi_search_dedupe(keywords, per_keyword=10, total_limit=limit)


def safety_search(community: str, city: str = "",
                  risk_keywords: list[str] | None = None,
                  limit: int = 20) -> list[dict]:
    """安全事件搜索。risk_keywords 由 safety_keywords.yaml 提供。

    反爬考虑：调用量 = len(risk_keywords)，警告期建议 ≤ 5 个关键词。
    """
    if risk_keywords is None:
        risk_keywords = ["凶案", "跳楼", "火灾", "入室", "纠纷"]
    # 强制上限 5 个，防止 safety_checker 传太多关键词触发反爬
    risk_keywords = risk_keywords[:5]
    queries = [f"{community} {kw}" for kw in risk_keywords]
    if city:
        queries = [f"{city} {q}" for q in queries]
    return _multi_search_dedupe(queries, per_keyword=8, total_limit=limit)


def single_woman_reviews(community: str, city: str = "", limit: int = 10) -> list[dict]:
    """女生独居视角（治安 / 物业 / 夜路）。"""
    keywords = [
        f"{community} 独居",
        f"{community} 女生 安全",
    ]
    if city:
        keywords = [f"{city} {kw}" for kw in keywords]
    return _multi_search_dedupe(keywords, per_keyword=6, total_limit=limit)


def pet_friendly_check(community: str, city: str = "", limit: int = 10) -> list[dict]:
    keywords = [
        f"{community} 养狗",
        f"{community} 养猫",
    ]
    if city:
        keywords = [f"{city} {kw}" for kw in keywords]
    return _multi_search_dedupe(keywords, per_keyword=6, total_limit=limit)


# ---------------------------------------------------------------------------
# 多关键词搜索 + 去重（保持串行，反爬保护）
# ---------------------------------------------------------------------------
def _multi_search_dedupe(keywords: list[str], per_keyword: int = 10,
                         total_limit: int = 30) -> list[dict]:
    """遍历多个 keyword，每个串行 search（受 Semaphore(1) 限制，无法并发）。

    旧版用 parallel_map(max_workers=4)，但因为 Semaphore(1) 实际还是串行 + 排队，
    反而占着信号量等导致更慢。直接用 for 串行更直观。
    """
    if not is_available():
        return []
    seen: dict[str, dict] = {}
    for kw in keywords:
        if _xhs_circuit_broken:
            break
        batch = search_feeds(kw, per_keyword)
        for f in batch:
            fid = f.get("feed_id")
            if not fid or fid in seen:
                continue
            seen[fid] = f
    items = list(seen.values())
    # 按互动量降序
    items.sort(
        key=lambda x: x.get("likes", 0) + x.get("favorites", 0) + x.get("comments", 0),
        reverse=True,
    )
    return items[:total_limit]
