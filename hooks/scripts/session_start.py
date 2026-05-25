#!/usr/bin/env python3
"""SessionStart hook — house-hunter 启动时的快速健康检查。

仅在用户明确触发 /house-hunter 时这个 hook 才显著影响体验，
所以这里只做轻量提醒（不主动启动服务）。
"""

from __future__ import annotations

import os
import sys

# Add scripts/ to path
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(SKILL_ROOT, "scripts"))

try:
    from _common import (  # type: ignore
        check_python_deps, check_baidu_map_key,
        find_xhs_skills_root, check_xhs_bridge_running,
    )
except Exception:
    sys.exit(0)


def main() -> None:
    deps_ok = all(check_python_deps().values())
    baidu_ok = check_baidu_map_key()
    xhs_ok = bool(find_xhs_skills_root()) and check_xhs_bridge_running()

    issues = []
    if not deps_ok:
        issues.append("Python 依赖未装")
    if not baidu_ok:
        issues.append("百度地图 Key 未配置")
    if not xhs_ok:
        issues.append("xiaohongshu-skills 不可用")

    if issues and "house-hunter" in os.environ.get("CLAUDE_ARGS", "").lower():
        print(f"[house-hunter] 启动前提醒: {', '.join(issues)} — 详见 SKILL.md Step 0", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
