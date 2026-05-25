"""Housing Bridge 客户端 — 通过本地 bridge_server 抓房产平台数据。

skill 端调用入口。封装：
  1. 跟 :9334 的 HTTP 通信
  2. 多站点 fallback（D10：lianjia → ke → ziroom → anjuke → 58 → fang）
  3. 返回统一 schema（CommunityInfo / Listing / PriceInfo）

降级行为：
  - bridge_server 没启动 → fetch_via_bridge 返 None，上层 fallback 到百度 POI
  - extension 未登录任一站点 → 返 None
  - 所有 adapter 失败 → 返 None
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _common import cached  # type: ignore
from sources.site_adapters import (  # type: ignore
    CommunityInfo, Listing, PriceInfo, SiteAdapter,
    all_adapters, get_adapter,
)

LOGGER = logging.getLogger("housing_bridge")

BRIDGE_URL = os.environ.get("HOUSING_BRIDGE_URL", "http://127.0.0.1:9334")
DEFAULT_FETCH_TIMEOUT_S = 60      # 跟 bridge_server 的 TASK_RESULT_TIMEOUT_S 对齐
HEALTH_CACHE_TTL_S = 5            # 健康检查结果缓存


# ───────────────────────── 基础 HTTP 客户端 ─────────────────────────
def _http_post_json(path: str, payload: dict, timeout_s: float) -> dict | None:
    url = BRIDGE_URL.rstrip("/") + path
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read().decode("utf-8"))
            data["_http_status"] = e.code
            return data
        except Exception:
            return {"error": f"HTTP {e.code}", "_http_status": e.code}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"error": f"bridge unreachable: {e}"}


def _http_get_json(path: str, timeout_s: float = 5.0) -> dict | None:
    url = BRIDGE_URL.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


# ───────────────────────── 健康状态（带短缓存）─────────────────────────
_health_cache: dict[str, Any] = {"ts": 0, "data": None}
_health_lock = threading.Lock()


def get_bridge_health() -> dict | None:
    """返回 bridge_server 的 /health 状态。带 5s 缓存。"""
    with _health_lock:
        if time.time() - _health_cache["ts"] < HEALTH_CACHE_TTL_S and _health_cache["data"]:
            return _health_cache["data"]
        data = _http_get_json("/health", timeout_s=2.0)
        if data:
            _health_cache["ts"] = time.time()
            _health_cache["data"] = data
        return data


def is_bridge_running() -> bool:
    data = get_bridge_health()
    return bool(data and data.get("ok"))


def get_logged_in_sites() -> list[str]:
    """返回 extension 当前已登录的站点列表（key 同 adapter.SITE_NAME）。"""
    data = get_bridge_health()
    if not data:
        return []
    return list(data.get("logged_in_sites") or [])


def is_extension_connected() -> bool:
    data = get_bridge_health()
    return bool(data and data.get("extension_connected"))


def quota_remaining() -> int:
    data = get_bridge_health()
    if not data:
        return 0
    return int(data.get("quota_remaining", 0))


# ───────────────────────── 核心：fetch URL via bridge ─────────────────────────
def fetch_via_bridge(url: str, timeout_s: float = DEFAULT_FETCH_TIMEOUT_S) -> dict | None:
    """通过 chrome extension 抓 URL，返回 dict:
        {"status": int, "html": str, "looks_like_login": bool, "final_url": str}
    or None on failure.

    失败原因记录在日志，让上层走 fallback。
    """
    result = _http_post_json("/fetch", {"url": url, "timeout_s": timeout_s},
                             timeout_s=timeout_s + 5)
    if result is None:
        LOGGER.warning("[bridge] unreachable when fetching %s", url[:80])
        return None
    if "error" in result:
        LOGGER.warning("[bridge] %s → %s", url[:80], result["error"])
        return None
    if result.get("status") and 200 <= int(result["status"]) < 300:
        return result
    LOGGER.warning("[bridge] %s → HTTP %s", url[:80], result.get("status"))
    return result  # 仍然返回，让 caller 判断（可能是 302 到登录页）


@cached("housing_bridge_html", ttl_seconds=86400)
def _fetch_html_cached(url: str, timeout_s: float = DEFAULT_FETCH_TIMEOUT_S) -> str | None:
    """24h 缓存：拿 HTML 字符串。被 fetch_html() 包装，**只缓存成功结果**。"""
    r = fetch_via_bridge(url, timeout_s)
    if not r or r.get("looks_like_login"):
        return None
    return r.get("html")


def fetch_html(url: str, timeout_s: float = DEFAULT_FETCH_TIMEOUT_S) -> str | None:
    """便捷版：拿 HTML 字符串。失败 (None) 不入缓存（避免 negative caching）。"""
    cached_val = _fetch_html_cached(url, timeout_s)
    if cached_val:
        return cached_val
    # cache hit 是 None 时（旧失败 / 还未访问过）→ 不读缓存，重 fetch
    # 简单做法：cache 装饰器已经被调用过；这里再发 fetch 会再走 cache 命中 None
    # 所以直接绕过 cache 重新调 underlying fetch
    r = fetch_via_bridge(url, timeout_s)
    if not r or r.get("looks_like_login"):
        return None
    html = r.get("html")
    # 成功后手动写入缓存（用 _fetch_html_cached 的 key 让下次命中）
    if html:
        from _common import _cache_key, _cache_dir  # type: ignore
        import os, json as _json, time as _time
        try:
            key = _cache_key("housing_bridge_html", (url, timeout_s))
            path = os.path.join(_cache_dir, key + ".json")
            os.makedirs(_cache_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                _json.dump({"ts": _time.time(), "value": html}, f, ensure_ascii=False)
        except Exception:
            pass
    return html


# ───────────────────────── 高层 API：跨多个 adapter 自动 fallback ─────────────────────────
def search_communities(city: str, district: str | None,
                       prefer_sites: list[str] | None = None,
                       limit: int = 10) -> tuple[list[CommunityInfo], str | None]:
    """按城市/区搜小区，自动 fallback 多站点。

    Returns (communities, source_used)。失败返 ([], None)。
    """
    if not is_bridge_running():
        return [], None
    logged_in = set(get_logged_in_sites())
    adapters = _adapter_candidates(prefer_sites, must_logged_in=logged_in)

    for adapter in adapters:
        if city not in adapter.SUPPORTED_CITIES:
            continue
        url = adapter.search_community_url(city, district)
        if not url:
            continue
        html = fetch_html(url)
        if not html:
            LOGGER.info("[%s] search failed/login → try next", adapter.SITE_NAME)
            continue
        items = adapter.parse_search(html, city)
        if items:
            return items[:limit], adapter.SITE_NAME
    return [], None


def get_community_detail(community_id: str, city: str,
                         site: str,
                         prefer_sites: list[str] | None = None) -> CommunityInfo | None:
    """拿单个小区的详情。优先指定 site，失败再 fallback。"""
    if not is_bridge_running():
        return None

    candidates = [site]
    if prefer_sites:
        candidates += [s for s in prefer_sites if s not in candidates]
    # 同公司 fallback（lianjia ↔ ke）
    if site == "lianjia":
        candidates.append("ke")
    elif site == "ke":
        candidates.append("lianjia")

    logged_in = set(get_logged_in_sites())
    for s in candidates:
        if s not in logged_in:
            continue
        adapter = get_adapter(s)
        if not adapter:
            continue
        url = adapter.community_detail_url(community_id, city)
        if not url:
            continue
        html = fetch_html(url)
        if not html:
            continue
        info = adapter.parse_community_detail(html, community_id, city)
        if info:
            return info
    return None


def get_community_listings(community_id: str, city: str,
                           site: str) -> PriceInfo | None:
    """拿小区挂牌价分布。"""
    if not is_bridge_running():
        return None
    logged_in = set(get_logged_in_sites())
    # 同公司 fallback
    candidates = [site]
    if site == "lianjia":
        candidates.append("ke")
    elif site == "ke":
        candidates.append("lianjia")

    for s in candidates:
        if s not in logged_in:
            continue
        adapter = get_adapter(s)
        if not adapter:
            continue
        url = adapter.listings_url(community_id, city)
        if not url:
            continue
        html = fetch_html(url)
        if not html:
            continue
        prices = adapter.parse_listings(html, community_id, city)
        if prices and prices.total_listings > 0:
            return prices
    return None


# ───────────────────────── adapter 候选筛选 ─────────────────────────
def _adapter_candidates(prefer_sites: list[str] | None,
                        must_logged_in: set[str]) -> list[SiteAdapter]:
    """根据偏好顺序 + 登录态过滤，返回可用 adapter 列表。"""
    if prefer_sites:
        ordered = [get_adapter(s) for s in prefer_sites]
    else:
        ordered = all_adapters()
    ordered = [a for a in ordered if a]
    if must_logged_in:
        ordered = [a for a in ordered if a.SITE_NAME in must_logged_in]
    return ordered


# ───────────────────────── CLI smoke test ─────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--health", action="store_true")
    p.add_argument("--fetch", type=str, help="URL to fetch via bridge")
    args = p.parse_args()

    if args.health:
        d = get_bridge_health()
        print(json.dumps(d, ensure_ascii=False, indent=2) if d else "bridge not running")
    elif args.fetch:
        r = fetch_via_bridge(args.fetch)
        if r:
            print(f"status: {r.get('status')}")
            print(f"final_url: {r.get('final_url')}")
            print(f"length: {r.get('content_length')}")
            print(f"looks_like_login: {r.get('looks_like_login')}")
            html = r.get('html') or ""
            print(f"head (200): {html[:200]}")
        else:
            print("fetch failed")
