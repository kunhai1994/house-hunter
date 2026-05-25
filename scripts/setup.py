#!/usr/bin/env python3
"""house-hunter setup: 安装 Python 依赖、创建目录、检查 xiaohongshu-skills 可用性。

可重复运行（幂等）。
"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (  # type: ignore
    HOUSE_HUNTER_DIR, CACHE_DIR_DEFAULT, REPORT_DIR,
    find_skill_root,
    find_xhs_skills_root,
    check_xhs_bridge_running, check_xhs_skills_python_deps,
    check_baidu_map_key, check_amap_key, check_tianditu_key, check_python_deps,
    detect_chrome_path, check_rod_browser_bin,
    detect_shell_rc, upsert_shell_var,
    ok, fail, info, warn,
)


REQUIRED_PIP_PKGS = ["pyyaml", "jinja2"]
XHS_SKILLS_PIP_PKGS = ["requests", "websockets", "python-socks"]


def install_python_deps() -> bool:
    deps = check_python_deps()
    missing = [m for m, installed in deps.items() if not installed]
    if not missing:
        ok("Python 依赖已就绪 (pyyaml, jinja2)")
        return True

    info(f"缺失依赖: {', '.join(missing)} — 正在安装...")
    pip_pkgs = []
    for m in missing:
        if m == "yaml":
            pip_pkgs.append("pyyaml")
        elif m == "jinja2":
            pip_pkgs.append("jinja2")
    # 第一次尝试：标准方式
    cmd = [sys.executable, "-m", "pip", "install", "--user", "--quiet", *pip_pkgs]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        ok(f"已安装: {', '.join(pip_pkgs)}")
        return True
    except subprocess.CalledProcessError:
        pass

    # 第二次尝试：处理 Homebrew Python 的 PEP 668
    info("检测到 PEP 668 限制，尝试 --break-system-packages 安装到用户目录...")
    cmd2 = [sys.executable, "-m", "pip", "install", "--user", "--quiet",
            "--break-system-packages", *pip_pkgs]
    try:
        subprocess.run(cmd2, check=True, capture_output=True)
        ok(f"已安装（用户目录）: {', '.join(pip_pkgs)}")
        return True
    except subprocess.CalledProcessError as e:
        fail(f"pip install 失败: {e}")
        info(f"  请手动运行: pip3 install --user --break-system-packages {' '.join(pip_pkgs)}")
        return False


def ensure_dirs() -> None:
    for d in [HOUSE_HUNTER_DIR, CACHE_DIR_DEFAULT, REPORT_DIR]:
        os.makedirs(d, exist_ok=True)
    ok(f"目录就绪: {HOUSE_HUNTER_DIR}")
    ok(f"报告目录: {REPORT_DIR}")


def setup_rod_browser() -> bool:
    """检测系统 Chrome / Chromium 路径，写入 ROD_BROWSER_BIN。

    这一步**很关键** — 不设置时 rod 库会尝试自动下载 Chromium，
    并发场景下下载缓冲区累积可能吃光内存（实测 55GB 事故）。
    """
    set_ok, current = check_rod_browser_bin()
    if set_ok:
        ok(f"ROD_BROWSER_BIN 已配置: {current}")
        return True

    if current and not set_ok:
        warn(f"ROD_BROWSER_BIN 设置了 {current} 但路径无效，重新检测...")

    info("查找系统 Chrome / Chromium / Edge / Brave...")
    path = detect_chrome_path()
    if not path:
        warn("未找到任何浏览器 — xhs-mcp 可能触发 rod 自动下载（高风险）")
        info("  解决方案：")
        info("  - macOS: 从 https://chrome.google.com 下载安装 Google Chrome")
        info("  - Linux (Debian/Ubuntu): sudo apt install chromium-browser")
        info("  - Linux (Fedora/RHEL): sudo dnf install chromium")
        return False

    # 验证：跑一下 --version
    try:
        result = subprocess.run([path, "--version"], capture_output=True, timeout=5)
        version = result.stdout.decode("utf-8", errors="replace").strip()
        if not version:
            version = result.stderr.decode("utf-8", errors="replace").strip()
        version = version or "?"
    except subprocess.TimeoutExpired:
        warn(f"找到 {path} 但 --version 超时")
        return False
    except Exception as e:
        warn(f"找到 {path} 但运行失败: {e}")
        return False

    ok(f"找到浏览器: {path}")
    info(f"  版本: {version}")

    # 持久化到 shell config
    rc_path = detect_shell_rc()
    upsert_shell_var(rc_path, "ROD_BROWSER_BIN", path,
                     section_tag="house-hunter — xhs-mcp 浏览器路径（避免 rod 自动下载内存爆炸）")
    os.environ["ROD_BROWSER_BIN"] = path
    ok(f"已写入 ROD_BROWSER_BIN 到 {rc_path}")
    return True


def install_xhs_skills_deps() -> bool:
    """安装 xhs-skills 需要的 Python 包（requests / websockets / python-socks）。"""
    deps = check_xhs_skills_python_deps()
    missing_keys = [k for k, v in deps.items() if not v]
    if not missing_keys:
        ok("xhs-skills Python 依赖已就绪")
        return True

    # 映射 import 名 → pip 包名
    pip_name = {
        "requests": "requests",
        "websockets": "websockets",
        "python_socks": "python-socks",
    }
    missing_pip = [pip_name[k] for k in missing_keys]
    info(f"安装 xhs-skills 依赖: {', '.join(missing_pip)}")

    # 国内 pypi 慢，先试默认源，再回退清华镜像
    sources = ["", "-i https://pypi.tuna.tsinghua.edu.cn/simple"]
    for source_arg in sources:
        cmd = [sys.executable, "-m", "pip", "install", "--user", "--quiet",
               "--break-system-packages", *missing_pip]
        if source_arg:
            cmd[7:7] = source_arg.split()  # 插入 -i 选项
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            ok(f"已安装: {', '.join(missing_pip)}")
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue

    fail(f"pip install 失败，请手动跑: pip3 install --user --break-system-packages {' '.join(missing_pip)}")
    return False


def check_xhs() -> None:
    """诊断 xiaohongshu-skills 安装状态 + bridge_server 运行情况。"""
    skills_root = find_xhs_skills_root()
    if skills_root:
        ok(f"xiaohongshu-skills 项目: {skills_root}")
        # 装依赖（一键自动）
        install_xhs_skills_deps()

        # bridge_server 状态
        if check_xhs_bridge_running():
            ok("bridge_server 运行中 (port 9333)")
        else:
            warn("bridge_server 未运行")
            info(f"  请在自己终端前台启动（保留窗口）：")
            info(f"    cd {skills_root}")
            info(f"    python3 scripts/bridge_server.py")
            info(f"  另外确保 Chrome 装了 XHS Bridge 扩展（chrome://extensions/）")
    else:
        warn("未找到 xiaohongshu-skills 项目")
        info("  推荐安装路径: ~/workspace/tools/xiaohongshu-mcp/xiaohongshu-skills")
        info("  github: https://github.com/autoclaw-cc/xiaohongshu-skills")
        info("  下载后跑 setup.py 自动检测")


def check_map_keys() -> None:
    if check_baidu_map_key():
        ok("百度地图 API Key 有效")
    else:
        warn("百度地图 API Key 未配置或无效")
        info("  申请: https://lbsyun.baidu.com/apiconsole/key")
        info("  设置环境变量: export BAIDU_MAPS_API_KEY=<your_ak>")

    if check_amap_key():
        ok("高德地图 API Key 有效")
    else:
        warn("高德地图 API Key 未配置或无效（备用源）")
        info("  申请: https://console.amap.com/dev/key/app")
        info("  设置环境变量: export AMAP_MAPS_API_KEY=<your_key>")

    if check_tianditu_key():
        ok("天地图 API Key 有效（第 3 fallback，每日 1 万次免费）")
    else:
        warn("天地图 API Key 未配置或无效（强烈推荐配置以减轻限流）")
        info("  申请: http://lbs.tianditu.gov.cn/authorization/authorization.html")
        info("  设置环境变量: export TIANDITU_API_KEY=<your_tk>")


def main() -> None:
    print("\n🏠 house-hunter setup\n")

    skill_root = find_skill_root()
    if skill_root:
        ok(f"Skill 根目录: {skill_root}")
    else:
        warn("未自动找到 SKILL_ROOT — 你可能正在开发模式下")

    print("\n[1/5] Python 依赖")
    deps_ok = install_python_deps()

    print("\n[2/5] 目录结构")
    ensure_dirs()

    print("\n[3/5] 地图 API Key")
    check_map_keys()

    print("\n[4/5] xhs-mcp 浏览器路径（关键！避免内存炸弹）")
    setup_rod_browser()

    print("\n[5/5] 小红书后端 (xiaohongshu-skills)")
    check_xhs()

    print()
    if deps_ok:
        ok("setup 完成。详细健康检查请运行: python3 scripts/status.py --json")
    else:
        fail("setup 部分失败，请按上方提示修复后重试")
        sys.exit(1)


if __name__ == "__main__":
    main()
