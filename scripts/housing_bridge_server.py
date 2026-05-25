#!/usr/bin/env python3
"""Housing Bridge Server — house-hunter 配套本地服务

跑在 :9334，跟 Chrome Extension（Housing Bridge）配对工作。

架构：
  skill (Python)    →  POST /fetch        →  阻塞等 task 完成
                                              │
                                              ↓
                                       任务队列（pending_tasks）
                                              │
  extension (Chrome) ←  GET /poll        ←  long-poll 取任务
                    →  POST /result      →  唤醒 skill 的 future
                    →  POST /heartbeat   →  报告登录态

启动：
  python3 scripts/housing_bridge_server.py            # 默认 :9334
  python3 scripts/housing_bridge_server.py --port X   # 自定义
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOGGER = logging.getLogger("housing-bridge")
DEFAULT_PORT = 9334

# ───────────────────────── 安全/限速参数 ─────────────────────────
MAX_SESSION_FETCHES = 200             # 单 server 进程生命周期总 fetch 上限（cache 后通常用不到）
MIN_FETCH_INTERVAL_S = 3.0            # 两次任务下发之间最少间隔
POLL_LONG_TIMEOUT_S = 30              # extension long-poll 服务端挂起上限
TASK_RESULT_TIMEOUT_S = 60            # 一个 task 从下发到拿到结果的总超时

# 支持的房产站点（跟 extension manifest 对齐）
SUPPORTED_HOSTS = {
    "lianjia.com", "ke.com", "ziroom.com",
    "anjuke.com", "58.com", "fang.com",
}


def host_in_scope(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
        return any(host == h or host.endswith("." + h) for h in SUPPORTED_HOSTS)
    except Exception:
        return False


# ───────────────────────── Bridge 核心 ─────────────────────────
class Bridge:
    """skill ↔ extension 之间的中间状态机。"""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self.pending: deque[dict] = deque()           # 还没被 extension 取的任务
        self.results: dict[str, dict] = {}             # task_id → result
        self.events: dict[str, threading.Event] = {}   # task_id → skill 端等待 evt
        self.heartbeats: dict[str, dict] = {}          # ext_id → 最近一次心跳

        self.total_dispatched = 0
        self.last_dispatch_at = 0.0

    # ──── skill 端 ────
    def submit_task(self, url: str, timeout_s: float = TASK_RESULT_TIMEOUT_S) -> dict | None:
        """提交任务并阻塞等结果。失败返 None / dict 含 error。"""
        if not host_in_scope(url):
            return {"error": f"URL out of scope: {url}"}

        # 配额检查
        if self.total_dispatched >= MAX_SESSION_FETCHES:
            return {"error": f"session quota exhausted ({MAX_SESSION_FETCHES})"}

        task_id = uuid.uuid4().hex[:16]
        evt = threading.Event()
        with self.cond:
            self.events[task_id] = evt
            self.pending.append({"task_id": task_id, "url": url, "timeout_ms": 15000})
            self.cond.notify_all()  # 唤醒可能正在等的 extension

        if not evt.wait(timeout=timeout_s):
            # 超时清理
            with self.cond:
                self.events.pop(task_id, None)
                self.results.pop(task_id, None)
                # 任务可能还在 pending 队列里 → 清掉
                self.pending = deque(t for t in self.pending if t["task_id"] != task_id)
            return {"error": f"timeout waiting for extension result ({timeout_s}s)"}

        with self.lock:
            return self.results.pop(task_id, None) or {"error": "no result"}

    # ──── extension 端 ────
    def take_task(self, ext_id: str, timeout_s: float = POLL_LONG_TIMEOUT_S) -> dict | None:
        """extension long-poll 拉任务。返 None = 超时无任务。"""
        end = time.time() + timeout_s
        with self.cond:
            while True:
                # 速率限制：距上次下发 < MIN_FETCH_INTERVAL 时，等
                wait_until_dispatch = self.last_dispatch_at + MIN_FETCH_INTERVAL_S - time.time()
                if self.pending and wait_until_dispatch <= 0:
                    task = self.pending.popleft()
                    self.total_dispatched += 1
                    self.last_dispatch_at = time.time()
                    LOGGER.info("dispatch task=%s ext=%s url=%s (#%d)",
                                task["task_id"], ext_id[:8], task["url"][:80],
                                self.total_dispatched)
                    return task
                # 计算下一次最早唤醒时间
                next_wakeup_in = min(
                    end - time.time(),
                    max(wait_until_dispatch, 0.0) if self.pending else (end - time.time())
                )
                if next_wakeup_in <= 0:
                    return None
                self.cond.wait(timeout=next_wakeup_in)

    def submit_result(self, task_id: str, result: dict) -> bool:
        with self.cond:
            if task_id not in self.events:
                # 可能已经超时被清理
                return False
            self.results[task_id] = result
            evt = self.events.pop(task_id)
        evt.set()
        return True

    def update_heartbeat(self, ext_id: str, payload: dict) -> None:
        payload = {**payload, "received_at": time.time()}
        with self.lock:
            self.heartbeats[ext_id] = payload

    # ──── 状态汇报 ────
    def get_state(self) -> dict:
        now = time.time()
        with self.lock:
            ext_list = []
            for ext_id, hb in self.heartbeats.items():
                ext_list.append({
                    "ext_id": ext_id[:8],
                    "logged_in": hb.get("logged_in") or {},
                    "last_seen_s_ago": round(now - hb.get("received_at", now), 1),
                })

            # 任一 ext 已登录的站点取并集
            logged_in_sites: set[str] = set()
            for hb in self.heartbeats.values():
                if (now - hb.get("received_at", 0)) < 60:  # 1 分钟内活跃
                    for site, ok in (hb.get("logged_in") or {}).items():
                        if ok:
                            logged_in_sites.add(site)

            return {
                "extension_connected": any(
                    (now - hb.get("received_at", 0)) < 60
                    for hb in self.heartbeats.values()
                ),
                "extensions": ext_list,
                "logged_in_sites": sorted(logged_in_sites),
                "pending_tasks": len(self.pending),
                "active_tasks": len(self.events),
                "session_fetches": self.total_dispatched,
                "quota_remaining": max(0, MAX_SESSION_FETCHES - self.total_dispatched),
            }


BRIDGE = Bridge()


# ───────────────────────── HTTP server ─────────────────────────
class Handler(BaseHTTPRequestHandler):
    # 减少噪音 log
    def log_message(self, format: str, *args) -> None:
        LOGGER.debug("%s - %s", self.address_string(), format % args)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # CORS — extension 调本地，且 host_permissions 含 localhost；这里宽松放行
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 50 * 1024 * 1024:  # 50MB 上限（HTML 一般 < 1MB）
            return None
        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    # ─── OPTIONS preflight ───
    def do_OPTIONS(self) -> None:
        self._send_json(200, {})

    # ─── GET routes ───
    def do_GET(self) -> None:
        u = urlparse(self.path)
        if u.path == "/health":
            self._send_json(200, {"ok": True, "version": "1.0.0", **BRIDGE.get_state()})
            return
        if u.path == "/poll":
            qs = parse_qs(u.query)
            ext_id = (qs.get("ext_id") or [""])[0]
            task = BRIDGE.take_task(ext_id or "anon")
            if task:
                self._send_json(200, task)
            else:
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
            return
        self._send_json(404, {"error": "not found"})

    # ─── POST routes ───
    def do_POST(self) -> None:
        u = urlparse(self.path)
        body = self._read_json()

        if u.path == "/fetch":
            if not body or not body.get("url"):
                self._send_json(400, {"error": "missing url"})
                return
            url = body["url"]
            timeout_s = float(body.get("timeout_s") or TASK_RESULT_TIMEOUT_S)
            result = BRIDGE.submit_task(url, timeout_s=timeout_s)
            if not result:
                self._send_json(500, {"error": "no result"})
                return
            if "error" in result:
                # 区分前置错误（out of scope/quota）和 fetch 错误
                status = 503 if "extension" in result["error"] else \
                         429 if "quota" in result["error"] else \
                         400 if "scope" in result["error"] else 504
                self._send_json(status, result)
                return
            self._send_json(200, result)
            return

        if u.path == "/result":
            if not body or not body.get("task_id"):
                self._send_json(400, {"error": "missing task_id"})
                return
            ok = BRIDGE.submit_result(body["task_id"], {
                k: v for k, v in body.items() if k != "task_id"
            })
            self._send_json(200, {"ok": ok})
            return

        if u.path == "/heartbeat":
            if not body or not body.get("ext_id"):
                self._send_json(400, {"error": "missing ext_id"})
                return
            BRIDGE.update_heartbeat(body["ext_id"], body)
            self._send_json(200, {"ok": True})
            return

        self._send_json(404, {"error": "not found"})


# ───────────────────────── main ─────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(description="Housing Bridge Server")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    LOGGER.info("Housing Bridge listening on http://%s:%d", args.host, args.port)
    LOGGER.info("  /health   GET  状态")
    LOGGER.info("  /fetch    POST {url} → skill 用")
    LOGGER.info("  /poll     GET  ?ext_id=… → extension long-poll")
    LOGGER.info("  /result   POST {task_id, ...} → extension 上报")
    LOGGER.info("  /heartbeat POST {ext_id, logged_in} → extension 心跳")
    LOGGER.info("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Shutting down (Ctrl+C)")
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
