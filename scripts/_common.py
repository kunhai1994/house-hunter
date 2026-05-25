"""house-hunter 共享工具：路径、HTTP、缓存、并发、控制台输出。

所有 sources/ analyzers/ reports/ 模块都依赖此模块。
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HOUSE_HUNTER_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "house-hunter")
CACHE_DIR_DEFAULT = os.path.join(HOUSE_HUNTER_DIR, "cache")
REPORT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "House-Hunter")

# Multi-platform skill root discovery
SEARCH_DIRS = [
    os.environ.get("CLAUDE_PLUGIN_ROOT", ""),
    os.environ.get("OPENCLAW_SKILL_ROOT", ""),
    os.environ.get("GEMINI_EXTENSION_DIR", ""),
    os.path.expanduser("~/.claude/skills/house-hunter"),
    os.path.expanduser("~/.agents/skills/house-hunter"),
    os.path.expanduser("~/.codex/skills/house-hunter"),
    os.path.expanduser("~/.gemini/extensions/house-hunter"),
    os.path.expanduser("~/workspace/tools/house-hunter"),
]

XHS_SKILLS_SEARCH_DIRS = [
    os.environ.get("XHS_SKILLS_ROOT", ""),
    os.path.expanduser("~/.claude/skills/xiaohongshu-skills"),
    os.path.expanduser("~/.agents/skills/xiaohongshu-skills"),
    os.path.expanduser("~/workspace/tools/xiaohongshu-mcp/xiaohongshu-skills"),
    os.path.expanduser("~/workspace/tools/xiaohongshu-skills"),
]

# 已废弃 — 保留常量用于检测旧 mcp 是否在跑（status.py 提示用户不要用）
XHS_MCP_PORT = 18060
XHS_MCP_BASE = os.environ.get("XIAOHONGSHU_API_BASE", f"http://localhost:{XHS_MCP_PORT}")

# v2: xhs-skills bridge 监听端口
XHS_BRIDGE_PORT = 9333


def find_skill_root() -> str | None:
    for d in SEARCH_DIRS:
        if d and os.path.isfile(os.path.join(d, "SKILL.md")) \
                and os.path.isdir(os.path.join(d, "scripts")):
            return d
    return None


def find_xhs_skills_root() -> str | None:
    """查找 xiaohongshu-skills 安装路径（v2 主要方式）。"""
    for d in XHS_SKILLS_SEARCH_DIRS:
        if d and os.path.isfile(os.path.join(d, "scripts", "cli.py")):
            return d
    return None


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------
def _color(code: str, msg: str) -> str:
    if not sys.stdout.isatty():
        return msg
    return f"\033[{code}m{msg}\033[0m"


def ok(msg: str) -> None:
    print(f"  {_color('32', '✅')} {msg}")


def fail(msg: str) -> None:
    print(f"  {_color('31', '❌')} {msg}")


def info(msg: str) -> None:
    print(f"  {_color('36', 'ℹ️ ')} {msg}")


def warn(msg: str) -> None:
    print(f"  {_color('33', '⚠️ ')} {msg}")


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------
DEFAULT_UA = "house-hunter/1.0 (+https://github.com/kunhai1994/house-hunter)"


def http_get(url: str, *, timeout: int = 10, headers: dict | None = None) -> str | None:
    """HTTP GET 整体 wall-clock timeout 上限 = timeout + 2s。

    历史教训：urllib `urlopen(timeout=N)` 的 timeout 是 **每次 socket recv** 而非整体 deadline。
    SSL 服务器慢吐数据（每次 read 都在 timeout 内但量很少）时可累积卡死几分钟。
    包一层 threading 强制整体上限。
    """
    import threading

    result: dict[str, Any] = {}

    def _worker():
        h = {"User-Agent": DEFAULT_UA}
        if headers:
            h.update(headers)
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                encoding = (resp.headers.get("Content-Encoding") or "").lower()
                if encoding == "gzip":
                    import gzip
                    data = gzip.decompress(data)
                elif encoding == "deflate":
                    import zlib
                    try:
                        data = zlib.decompress(data)
                    except zlib.error:
                        data = zlib.decompress(data, -zlib.MAX_WBITS)
                elif encoding == "br":
                    try:
                        import brotli  # type: ignore
                        data = brotli.decompress(data)
                    except ImportError:
                        result['data'] = None
                        return
                charset = resp.headers.get_content_charset() or "utf-8"
                result['data'] = data.decode(charset, errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            result['data'] = None

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout + 2)
    if t.is_alive():
        return None  # 整体超时，daemon 线程自生自灭
    return result.get('data')


def http_get_json(url: str, *, timeout: int = 10, headers: dict | None = None) -> Any:
    text = http_get(url, timeout=timeout, headers=headers)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def http_post_json(url: str, payload: dict, *, timeout: int = 15,
                   headers: dict | None = None) -> Any:
    """HTTP POST JSON 整体 wall-clock timeout（同 http_get 的修复）。"""
    import threading

    body = json.dumps(payload).encode("utf-8")
    h = {"User-Agent": DEFAULT_UA, "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    result: dict[str, Any] = {}

    def _worker():
        try:
            req = urllib.request.Request(url, data=body, headers=h, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                result['data'] = json.loads(data.decode("utf-8", errors="replace"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
                json.JSONDecodeError):
            result['data'] = None

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout + 2)
    if t.is_alive():
        return None
    return result.get('data')


# ---------------------------------------------------------------------------
# Disk cache (JSON, TTL)
# ---------------------------------------------------------------------------
_cache_dir = CACHE_DIR_DEFAULT
_cache_lock = threading.Lock()


def set_cache_dir(path: str) -> None:
    global _cache_dir
    _cache_dir = path
    os.makedirs(_cache_dir, exist_ok=True)


def _cache_key(namespace: str, key: Any) -> str:
    raw = json.dumps(key, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"{namespace}-{digest}"


def cache_get(namespace: str, key: Any, ttl_seconds: int) -> Any:
    fname = _cache_key(namespace, key) + ".json"
    fpath = os.path.join(_cache_dir, fname)
    if not os.path.isfile(fpath):
        return None
    try:
        with _cache_lock:
            mtime = os.path.getmtime(fpath)
        if time.time() - mtime > ttl_seconds:
            return None
        with open(fpath, "r", encoding="utf-8") as f:
            entry = json.load(f)
        return entry.get("value")
    except Exception:
        return None


def cache_set(namespace: str, key: Any, value: Any) -> None:
    os.makedirs(_cache_dir, exist_ok=True)
    fname = _cache_key(namespace, key) + ".json"
    fpath = os.path.join(_cache_dir, fname)
    entry = {"key": key, "value": value, "ts": time.time()}
    try:
        with _cache_lock:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False)
    except Exception:
        pass


def cached(namespace: str, ttl_seconds: int = 86400):
    """Decorator: cache function result by (args, kwargs) tuple."""
    def deco(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = {"args": args, "kwargs": kwargs}
            hit = cache_get(namespace, key, ttl_seconds)
            if hit is not None:
                return hit
            result = fn(*args, **kwargs)
            if result is not None:
                cache_set(namespace, key, result)
            return result
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Concurrency helpers
# ---------------------------------------------------------------------------
def parallel_map(fn: Callable, items: list, *, max_workers: int = 8,
                 timeout: int = 60) -> list:
    """Apply fn to items in parallel. Preserves order. Failed/timeout items return None.

    Timeout 触发时**不再 raise**，返回 partial 结果（未完成 = None）。
    """
    if not items:
        return []
    results: list = [None] * len(items)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fn, item): idx for idx, item in enumerate(items)}
        try:
            for fut in as_completed(futures, timeout=timeout):
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                except Exception:
                    results[idx] = None
        except TimeoutError:
            # 整体超时：取消未完成的，返回已完成的部分
            for fut, idx in futures.items():
                if fut.done():
                    try:
                        results[idx] = fut.result()
                    except Exception:
                        results[idx] = None
                else:
                    fut.cancel()
                    results[idx] = None
    return results


# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------
EARTH_RADIUS_M = 6_371_000


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in meters."""
    rad = math.pi / 180
    p1 = lat1 * rad
    p2 = lat2 * rad
    dp = (lat2 - lat1) * rad
    dl = (lng2 - lng1) * rad
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Rate limiter (simple per-key token bucket)
# ---------------------------------------------------------------------------
class RateLimiter:
    """Per-key min-interval rate limiter (thread-safe)."""

    def __init__(self, min_interval_s: float):
        self.min_interval = min_interval_s
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, key: str = "default") -> None:
        with self._lock:
            last = self._last.get(key, 0.0)
            now = time.time()
            wait_s = self.min_interval - (now - last)
            if wait_s > 0:
                time.sleep(wait_s)
            self._last[key] = time.time()


# ---------------------------------------------------------------------------
# YAML loader (minimal — uses pyyaml if available, else fallback)
# ---------------------------------------------------------------------------
def load_yaml(path: str) -> dict:
    """Load YAML. Requires pyyaml."""
    try:
        import yaml  # type: ignore
    except ImportError:
        fail("pyyaml not installed. Run: pip3 install pyyaml")
        raise
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Config loader (memoized)
# ---------------------------------------------------------------------------
_config_cache: dict[str, Any] = {}


def get_config(name: str) -> Any:
    """Load config by name (e.g., 'poi_categories' → config/poi_categories.yaml)."""
    if name in _config_cache:
        return _config_cache[name]
    root = find_skill_root() or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(root, "config", f"{name}.yaml"),
        os.path.join(root, "config", f"{name}.json"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            data = load_yaml(path) if path.endswith(".yaml") else load_json(path)
            _config_cache[name] = data
            return data
    raise FileNotFoundError(f"Config not found: {name} (searched {candidates})")


# ---------------------------------------------------------------------------
# Health checks (used by status.py and SKILL.md Step 0)
# ---------------------------------------------------------------------------
def check_xhs_running() -> bool:
    """已废弃 — 检测旧 xhs-mcp 是否在跑（用于警告用户应该停掉）。"""
    data = http_get_json(f"{XHS_MCP_BASE}/health", timeout=2)
    return isinstance(data, dict) and data.get("success") is True


def check_xhs_logged_in() -> bool:
    """已废弃 — 检测旧 xhs-mcp 登录状态。"""
    data = http_get_json(f"{XHS_MCP_BASE}/api/v1/login/status", timeout=8)
    if not isinstance(data, dict):
        return False
    return data.get("data", {}).get("is_logged_in") is True


# ---------------------------------------------------------------------------
# xhs-skills（v2）健康检查
# ---------------------------------------------------------------------------
def check_xhs_bridge_running() -> bool:
    """通过 9333 端口判断 bridge_server.py 是否在跑。"""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", XHS_BRIDGE_PORT), timeout=1):
            return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False


def check_xhs_skills_python_deps() -> dict:
    """xhs-skills 运行需要的 Python 包是否装了。"""
    deps = {"requests": False, "websockets": False, "python_socks": False}
    for name in deps:
        try:
            __import__(name)
            deps[name] = True
        except ImportError:
            pass
    return deps


def check_xhs_skills_available() -> bool:
    """组合判断：项目存在 + 依赖齐 → 可调用 cli.py。"""
    if find_xhs_skills_root() is None:
        return False
    if not all(check_xhs_skills_python_deps().values()):
        return False
    return True


def check_baidu_map_key() -> bool:
    """Quick API ping (geocoding for '北京')."""
    ak = os.environ.get("BAIDU_MAPS_API_KEY") or os.environ.get("BAIDU_MAP_AK")
    if not ak:
        return False
    url = f"https://api.map.baidu.com/geocoding/v3/?address=%E5%8C%97%E4%BA%AC&output=json&ak={ak}"
    data = http_get_json(url, timeout=5)
    return isinstance(data, dict) and data.get("status") == 0


def check_amap_key() -> bool:
    key = os.environ.get("AMAP_MAPS_API_KEY") or os.environ.get("AMAP_KEY")
    if not key:
        return False
    url = f"https://restapi.amap.com/v3/geocode/geo?address=北京&key={key}"
    url = urllib.parse.quote(url, safe=":/?=&")
    data = http_get_json(url, timeout=5)
    return isinstance(data, dict) and str(data.get("status")) == "1"


def check_tianditu_key() -> bool:
    """天地图 key 校验：用 search v2 ping 一次。"""
    import json as _json
    key = os.environ.get("TIANDITU_API_KEY") or os.environ.get("TDT_KEY")
    if not key:
        return False
    post_str = _json.dumps({
        "keyWord": "公园", "level": 12, "queryRadius": 5000,
        "pointLonlat": "116.40,39.90", "queryType": 3,
        "start": 0, "count": 1,
    }, ensure_ascii=False, separators=(",", ":"))
    params = urllib.parse.urlencode({"postStr": post_str, "type": "query", "tk": key})
    data = http_get_json(f"http://api.tianditu.gov.cn/v2/search?{params}", timeout=5)
    if not isinstance(data, dict):
        return False
    return (data.get("status") or {}).get("infocode") == 1000


def check_python_deps() -> dict:
    """Return a dict mapping module name → installed (bool)."""
    deps = ["yaml", "jinja2"]
    result = {}
    for mod in deps:
        try:
            __import__(mod)
            result[mod] = True
        except ImportError:
            result[mod] = False
    return result


# ---------------------------------------------------------------------------
# Chrome / Chromium 路径检测（关键：避免 rod 库自动下载触发内存爆炸）
# ---------------------------------------------------------------------------
def detect_chrome_path() -> str | None:
    """查找系统已安装的 Chrome / Chromium / Edge / Brave 二进制。

    返回第一个能找到且可执行的路径；找不到返回 None。
    优先级：Google Chrome > Chromium > Microsoft Edge > Brave。
    """
    import platform as _p
    import shutil

    system = _p.system()

    # macOS：标准 Application 路径
    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ]
        for p in candidates:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        return None

    # Linux：先查 PATH 再查常见绝对路径
    if system == "Linux":
        for name in ["google-chrome-stable", "google-chrome",
                     "chromium-browser", "chromium",
                     "microsoft-edge-stable", "microsoft-edge",
                     "brave-browser"]:
            p = shutil.which(name)
            if p:
                return p
        for p in ["/usr/bin/google-chrome", "/usr/bin/chromium-browser",
                  "/usr/bin/chromium", "/snap/bin/chromium",
                  "/opt/google/chrome/chrome"]:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
        return None

    # Windows / WSL：尝试常见路径
    if system == "Windows":
        for p in [
            "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
            "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        ]:
            if os.path.isfile(p):
                return p
        return None

    return None


def check_rod_browser_bin() -> tuple[bool, str | None]:
    """返回 (有效设置, 当前路径)。

    - (True, path)  : env 有 ROD_BROWSER_BIN 且文件存在可执行
    - (False, path) : env 设了但路径无效 → 需要重新检测
    - (False, None) : env 未设置
    """
    path = os.environ.get("ROD_BROWSER_BIN")
    if not path:
        return False, None
    if os.path.isfile(path) and os.access(path, os.X_OK):
        return True, path
    return False, path


# ---------------------------------------------------------------------------
# Shell rc 文件持久化（多个脚本共用：configure_key / setup ROD_BROWSER_BIN 等）
# ---------------------------------------------------------------------------
def detect_shell_rc() -> str:
    """优先 ~/.zshrc → ~/.bash_profile → ~/.bashrc，都不存在则创建 ~/.bash_profile。"""
    home = os.path.expanduser("~")
    for cand in [".zshrc", ".bash_profile", ".bashrc"]:
        p = os.path.join(home, cand)
        if os.path.isfile(p):
            return p
    return os.path.join(home, ".bash_profile")


def upsert_shell_var(rc_path: str, var: str, value: str,
                     section_tag: str = "house-hunter") -> None:
    """在 rc 文件中 upsert `export VAR="value"`，幂等。"""
    import re
    lines: list[str] = []
    if os.path.isfile(rc_path):
        with open(rc_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    pattern = re.compile(r'^\s*export\s+' + re.escape(var) + r'\s*=')
    new_line = f'export {var}="{value}"\n'

    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            with open(rc_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            return

    # 找不到既有行 → append
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    if section_tag and not any(section_tag in l for l in lines):
        lines.append(f"\n# {section_tag}\n")
    lines.append(new_line)

    with open(rc_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
