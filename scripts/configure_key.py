#!/usr/bin/env python3
"""一键持久化 API Key — 让用户「直接把 key 给 LLM 即可」的关键脚本。

LLM 在 SKILL.md Step 0 用法：
  python3 scripts/configure_key.py --baidu '<AK>' --amap '<KEY>' --tianditu '<TK>'

效果：
  1. 写到 shell 配置（自动检测 zsh / bash），下次新 shell 自动生效
  2. 把当前进程的 env var 也设上（status.py 立刻能 ping 通）
  3. 用 API ping 一下，验证 key 真的有效
"""

from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _common import (  # type: ignore
    check_baidu_map_key, check_amap_key, check_tianditu_key,
    detect_shell_rc, upsert_shell_var,
    ok, fail, info, warn,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="house-hunter: 持久化 API Key")
    parser.add_argument("--baidu", help="百度地图 AK（5000/天，fallback#1）")
    parser.add_argument("--amap", help="高德地图 Key（100/天，fallback#2）")
    parser.add_argument("--tianditu", help="天地图 tk（10000/天，fallback#3，国家测绘局）")
    parser.add_argument("--rc", help="shell 配置文件路径（默认自动检测）")
    parser.add_argument("--no-verify", action="store_true", help="跳过 API ping 校验")
    args = parser.parse_args()

    if not args.baidu and not args.amap and not args.tianditu:
        fail("至少需要 --baidu / --amap / --tianditu 中的一个")
        return 2

    rc_path = args.rc or detect_shell_rc()
    info(f"shell 配置文件: {rc_path}")

    if args.baidu:
        upsert_shell_var(rc_path, "BAIDU_MAPS_API_KEY", args.baidu,
                         section_tag="house-hunter — 地图 API Keys")
        os.environ["BAIDU_MAPS_API_KEY"] = args.baidu
        ok("已写入 BAIDU_MAPS_API_KEY")

    if args.amap:
        upsert_shell_var(rc_path, "AMAP_MAPS_API_KEY", args.amap,
                         section_tag="house-hunter — 地图 API Keys")
        os.environ["AMAP_MAPS_API_KEY"] = args.amap
        ok("已写入 AMAP_MAPS_API_KEY")

    if args.tianditu:
        upsert_shell_var(rc_path, "TIANDITU_API_KEY", args.tianditu,
                         section_tag="house-hunter — 地图 API Keys")
        os.environ["TIANDITU_API_KEY"] = args.tianditu
        ok("已写入 TIANDITU_API_KEY")

    if args.no_verify:
        info("跳过 API 校验。请手动跑 python3 scripts/status.py 确认。")
        return 0

    info("校验 key 是否有效（联网 ping）...")
    failed = []
    if args.baidu:
        if check_baidu_map_key():
            ok("百度地图 Key 有效")
        else:
            fail("百度地图 Key 校验失败 — 检查是否选了「服务端」+ IP 白名单 0.0.0.0/0")
            failed.append("baidu")
    if args.amap:
        if check_amap_key():
            ok("高德地图 Key 有效")
        else:
            fail("高德地图 Key 校验失败 — 检查是否选了「Web服务」类型")
            failed.append("amap")
    if args.tianditu:
        if check_tianditu_key():
            ok("天地图 Key 有效")
        else:
            fail("天地图 Key 校验失败 — 检查是否申请的是「服务端」类型")
            failed.append("tianditu")

    if failed:
        warn(f"以下 Key 无效: {', '.join(failed)}")
        warn("Key 已写入 shell 配置但未通过校验；请重新申请或检查后再试")
        return 1

    print()
    ok("配置完成！Key 已持久化，下次新 shell 自动生效")
    info(f"当前 shell 立即生效需要: source {rc_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
