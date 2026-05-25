#!/usr/bin/env python3
"""xhs-skills 健康探针 — 在做任何 xhs 调研之前必跑（v2）。

设计目的：
  - 验证 xhs-skills 项目存在 + Python 依赖装好
  - 验证 bridge_server 在跑（port 9333）
  - 用 cli.py check-login 验证扩展连上 + 已登录
  - 不发任何"消耗配额"的请求（不调 search 避免再触发反爬警告）

返回值：
  0  → 健康，可以使用 xhs 维度
  1  → 未运行 / 未登录 / 项目不存在（应降级，不要硬跑）
  2  → 致命错误（同样降级）

用法：
  python3 scripts/xhs_health_probe.py            # 人类可读
  python3 scripts/xhs_health_probe.py --json     # 机器可读
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _common import (  # type: ignore
    find_xhs_skills_root,
    check_xhs_bridge_running, check_xhs_skills_python_deps,
    ok, fail, info, warn,
)


def probe() -> dict:
    """执行健康探针。

    Returns: {"status": "ok|no_project|missing_deps|bridge_down|not_logged_in|error", ...}
    """
    result = {
        "status": "error",
        "checks": {},
        "elapsed_ms": 0,
    }
    t0 = time.time()

    # 1. 项目存在
    root = find_xhs_skills_root()
    if not root:
        result["status"] = "no_project"
        result["error"] = "未找到 xhs-skills（期望: ~/workspace/tools/xiaohongshu-mcp/xiaohongshu-skills）"
        return _finalize(result, t0)
    result["checks"]["project"] = root

    # 2. Python 依赖
    deps = check_xhs_skills_python_deps()
    missing = [k for k, v in deps.items() if not v]
    if missing:
        result["status"] = "missing_deps"
        result["error"] = f"缺少 Python 依赖: {missing}"
        return _finalize(result, t0)
    result["checks"]["python_deps"] = "ok"

    # 3. bridge_server 在跑
    if not check_xhs_bridge_running():
        result["status"] = "bridge_down"
        result["error"] = "bridge_server.py 未运行（port 9333）"
        return _finalize(result, t0)
    result["checks"]["bridge"] = "ok"

    # 4. 用 cli.py check-login（不发 search，避免反爬）
    cli = os.path.join(root, "scripts", "cli.py")
    try:
        r = subprocess.run(
            [sys.executable, cli, "check-login"],
            cwd=root,
            capture_output=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        result["status"] = "not_logged_in"
        result["error"] = "check-login 超时（>20s）"
        return _finalize(result, t0)
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"check-login 异常: {e}"
        return _finalize(result, t0)

    if r.returncode != 0:
        result["status"] = "not_logged_in"
        result["error"] = f"check-login exit {r.returncode}（需重新扫码）"
        return _finalize(result, t0)

    try:
        data = json.loads(r.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        result["status"] = "error"
        result["error"] = "check-login 输出不是 JSON"
        return _finalize(result, t0)

    if not data.get("logged_in"):
        result["status"] = "not_logged_in"
        result["error"] = "check-login 返回 logged_in=false"
        return _finalize(result, t0)

    result["checks"]["logged_in"] = "ok"
    result["status"] = "ok"
    return _finalize(result, t0)


def _finalize(result: dict, t0: float) -> dict:
    result["elapsed_ms"] = round((time.time() - t0) * 1000)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="xhs-skills 健康探针")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    r = probe()

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"\n🩺 xhs-skills 健康探针（{r['elapsed_ms']}ms）\n")
        for k, v in r.get("checks", {}).items():
            ok(f"{k}: {v}")
        if r["status"] == "ok":
            ok("xhs 健康，可以使用")
        elif r["status"] == "no_project":
            fail(f"未找到 xhs-skills 项目 — {r.get('error')}")
            info("从 https://github.com/autoclaw-cc/xiaohongshu-skills clone 后重新跑 setup.py")
        elif r["status"] == "missing_deps":
            fail(f"Python 依赖缺失 — {r.get('error')}")
            info("跑 python3 scripts/setup.py 自动安装")
        elif r["status"] == "bridge_down":
            fail(f"bridge_server 未运行 — {r.get('error')}")
            info("用户需在自己终端前台跑 python3 scripts/bridge_server.py")
        elif r["status"] == "not_logged_in":
            fail(f"小红书未登录 — {r.get('error')}")
            info("跑 python3 scripts/cli.py login 扫码登录")
        else:
            fail(f"探针失败：{r.get('error')}")

    if r["status"] == "ok":
        return 0
    if r["status"] in ("no_project", "missing_deps", "bridge_down", "not_logged_in"):
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
