#!/usr/bin/env python3
"""house-hunter 健康检查 — SKILL.md Step 0 调用此脚本判断环境是否就绪。

运行：
  python3 scripts/status.py            # 人类可读输出
  python3 scripts/status.py --json     # 机器可读输出（SKILL.md 解析此格式）

返回 JSON 结构：
{
  "all_ready": bool,
  "python_deps": { "yaml": bool, "jinja2": bool },
  "baidu_map_key": bool,
  "amap_key": bool,
  "xhs_research_found": bool,
  "xhs_mcp_running": bool,
  "xhs_logged_in": bool,
  "report_dir": str,
  "fixes": [ <action_id> ]            # 失败项对应的修复动作 ID
}

修复动作 ID 与 SKILL.md 的修复指引一一对应：
  install_python_deps, configure_baidu_key, configure_amap_key,
  install_xhs_research, start_xhs_mcp, login_xhs
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (  # type: ignore
    REPORT_DIR,
    find_skill_root,
    find_xhs_skills_root,
    check_xhs_bridge_running, check_xhs_skills_python_deps,
    check_baidu_map_key, check_amap_key, check_tianditu_key, check_python_deps,
    check_rod_browser_bin, detect_chrome_path,
    ok, fail, info, warn,
)


def collect() -> dict:
    deps = check_python_deps()

    xhs_skills_root = find_xhs_skills_root()
    xhs_skills_deps = check_xhs_skills_python_deps()
    xhs_skills_deps_ok = all(xhs_skills_deps.values()) if xhs_skills_root else False
    bridge_running = check_xhs_bridge_running()

    # Housing Bridge（链家/贝壳/自如/安居客/58/房天下 数据采集扩展）
    housing_state = _check_housing_bridge()

    result = {
        "skill_root": find_skill_root(),
        "report_dir": REPORT_DIR,
        "python_deps": deps,
        "baidu_map_key": check_baidu_map_key(),
        "amap_key": check_amap_key(),
        "tianditu_key": check_tianditu_key(),

        # xhs-skills (v2)
        "xhs_skills_found": xhs_skills_root is not None,
        "xhs_skills_root": xhs_skills_root,
        "xhs_skills_python_deps": xhs_skills_deps,
        "xhs_skills_python_deps_ok": xhs_skills_deps_ok,
        "xhs_bridge_running": bridge_running,

        # Housing Bridge (绕链家/贝壳/...反爬的浏览器扩展)
        "housing_bridge_running": housing_state["bridge_running"],
        "housing_extension_connected": housing_state["extension_connected"],
        "housing_logged_in_sites": housing_state["logged_in_sites"],
        "housing_quota_remaining": housing_state["quota_remaining"],

    }

    fixes: list[str] = []
    if not all(deps.values()):
        fixes.append("install_python_deps")
    if not result["baidu_map_key"]:
        fixes.append("configure_baidu_key")
    if not result["amap_key"]:
        fixes.append("configure_amap_key")
    if not result["tianditu_key"]:
        fixes.append("configure_tianditu_key")
    if not xhs_skills_root:
        fixes.append("install_xhs_skills")
    elif not xhs_skills_deps_ok:
        fixes.append("install_xhs_skills_deps")
    elif not bridge_running:
        fixes.append("start_xhs_bridge")
    # Housing Bridge fixes（可选 — 没装也能用百度POI兜底）
    if not housing_state["bridge_running"]:
        fixes.append("start_housing_bridge")
    elif not housing_state["extension_connected"]:
        fixes.append("install_housing_extension")
    elif not housing_state["logged_in_sites"]:
        fixes.append("login_housing_site")
    result["fixes"] = fixes

    # all_ready：基础功能（地图）就绪即可，xhs 和 housing-bridge 是 nice-to-have
    must_have = [
        all(deps.values()),
        result["baidu_map_key"],
    ]
    xhs_v2_ready = (xhs_skills_root and xhs_skills_deps_ok and bridge_running)
    housing_ready = (
        housing_state["bridge_running"]
        and housing_state["extension_connected"]
        and len(housing_state["logged_in_sites"]) > 0
    )
    nice_to_have = [
        result["amap_key"],
        xhs_v2_ready,
        housing_ready,
    ]
    result["all_ready"] = all(must_have)
    result["fully_ready"] = all(must_have) and all(nice_to_have)
    result["xhs_v2_ready"] = bool(xhs_v2_ready)
    result["housing_ready"] = bool(housing_ready)

    return result


def _check_housing_bridge() -> dict:
    """检测 Housing Bridge 状态（运行中 + 扩展连接 + 哪些站点已登录）。"""
    import socket as _socket
    out = {
        "bridge_running": False,
        "extension_connected": False,
        "logged_in_sites": [],
        "quota_remaining": 0,
    }
    # 先看端口是否在监听
    try:
        with _socket.create_connection(("127.0.0.1", 9334), timeout=1):
            out["bridge_running"] = True
    except (ConnectionRefusedError, _socket.timeout, OSError):
        return out

    # 端口在 → 调 /health
    try:
        from sources import housing_bridge  # type: ignore
        data = housing_bridge.get_bridge_health()
        if data:
            out["extension_connected"] = bool(data.get("extension_connected"))
            out["logged_in_sites"] = list(data.get("logged_in_sites") or [])
            out["quota_remaining"] = int(data.get("quota_remaining", 0))
    except Exception:
        pass
    return out


def render_human(r: dict) -> None:
    print("\n📊 house-hunter status\n")

    def check(label: str, value: bool, hint: str = "", required: bool = True) -> None:
        if value:
            ok(label)
        elif required:
            fail(f"{label}{f' — {hint}' if hint else ''}")
        else:
            warn(f"{label}{f' — {hint}' if hint else ''}")

    print("[必需]")
    check("Python pyyaml", r["python_deps"].get("yaml", False),
          "运行 python3 scripts/setup.py")
    check("Python jinja2", r["python_deps"].get("jinja2", False),
          "运行 python3 scripts/setup.py")
    check("百度地图 API Key", r["baidu_map_key"],
          "申请 AK 并 export BAIDU_MAPS_API_KEY=<ak>")

    print("\n[可选 / 推荐]")
    check("高德地图 API Key", r["amap_key"],
          "备用地图源（fallback#2）；export AMAP_MAPS_API_KEY=<key>", required=False)
    check("天地图 API Key（每日 1 万次免费）", r["tianditu_key"],
          "强推荐配置（fallback#3，国家测绘局）；export TIANDITU_API_KEY=<tk>",
          required=False)

    print("\n[小红书 — 推荐 xhs-skills]")
    check("xiaohongshu-skills 项目", r["xhs_skills_found"],
          "找不到时小红书功能不可用 — 见 SKILL.md Step 0.B", required=False)
    if r["xhs_skills_found"]:
        if r["xhs_skills_python_deps_ok"]:
            ok("  Python 依赖（requests / websockets / python_socks）")
        else:
            missing = [k for k, v in r["xhs_skills_python_deps"].items() if not v]
            warn(f"  Python 依赖缺失: {', '.join(missing)} — 运行 python3 scripts/setup.py")
        check("  bridge_server.py 运行中 (port 9333)", r["xhs_bridge_running"],
              "在 xhs-skills 目录前台跑 python3 scripts/bridge_server.py，并装 XHS Bridge 扩展",
              required=False)

    print("\n[Housing Bridge — 推荐（链家/贝壳/自如/安居客/58/房天下 数据采集）]")
    check("Housing Bridge server 运行中 (port 9334)", r["housing_bridge_running"],
          "前台跑 python3 scripts/housing_bridge_server.py — 见 SKILL.md Step 0.D",
          required=False)
    if r["housing_bridge_running"]:
        check("  Chrome 扩展已连接", r["housing_extension_connected"],
              "装扩展：chrome://extensions → 开发者模式 → 加载已解压 → 选 extension/",
              required=False)
        sites = r["housing_logged_in_sites"]
        if sites:
            ok(f"  已登录站点: {', '.join(sites)}")
        else:
            warn("  无已登录站点 — 请在 Chrome 里登录任一房产网站 (推荐 ke.com 贝壳)")
        if r["housing_quota_remaining"] is not None:
            info(f"  本会话配额剩余: {r['housing_quota_remaining']} / 80")

    print()
    if r["fully_ready"]:
        ok("所有系统就绪！可以使用 /house-hunter")
    elif r["all_ready"]:
        warn("基础功能可用；建议补全可选项以获得最佳效果")
    else:
        fail("基础功能不可用，请按提示修复")
        info(f"修复动作: {', '.join(r['fixes'])}")


def main() -> None:
    emit_json = "--json" in sys.argv
    r = collect()

    if emit_json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        sys.exit(0 if r["all_ready"] else 1)

    render_human(r)
    sys.exit(0 if r["all_ready"] else 1)


if __name__ == "__main__":
    main()
