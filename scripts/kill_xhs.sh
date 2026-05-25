#!/usr/bin/env bash
# 安全停止 xhs-skills bridge_server + 旧 xiaohongshu-mcp（如果在跑）
#
# 用法：
#   bash scripts/kill_xhs.sh
#
# 不会动用户已打开的 Chrome 窗口（bridge_server 只是个 WebSocket 服务，
# 它的"子进程"只有它自己，没有 Chromium）。

set -uo pipefail

echo "🧹 清理 xhs 相关进程..."

found_any=0

# v2: bridge_server.py
pids=$(pgrep -f "bridge_server.py" 2>/dev/null || true)
if [ -n "$pids" ]; then
    for pid in $pids; do
        pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || echo "")
        if [ -n "$pgid" ]; then
            echo "  → 终止进程组 $pgid（bridge_server PID=$pid）"
            kill -TERM -- "-$pgid" 2>/dev/null || true
        else
            kill -TERM "$pid" 2>/dev/null || true
        fi
        found_any=1
    done
fi

# v1（旧）: xiaohongshu-mcp / xiaohongshu-login
for pattern in "xiaohongshu-mcp" "xiaohongshu-login"; do
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        for pid in $pids; do
            pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || echo "")
            if [ -n "$pgid" ]; then
                echo "  → 终止进程组 $pgid（旧 $pattern PID=$pid）"
                kill -TERM -- "-$pgid" 2>/dev/null || true
            else
                kill -TERM "$pid" 2>/dev/null || true
            fi
            found_any=1
        done
    fi
done

# 等 1 秒，SIGKILL 兜底
if [ "$found_any" = "1" ]; then
    sleep 1
    for pattern in "bridge_server.py" "xiaohongshu-mcp" "xiaohongshu-login"; do
        pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            for pid in $pids; do
                pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || echo "")
                [ -n "$pgid" ] && kill -KILL -- "-$pgid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
            done
        fi
    done
fi

# 清掉旧 mcp 的 chromedp 临时目录（v1 残留）
for tmpdir in /tmp /var/folders /var/tmp; do
    if [ -d "$tmpdir" ]; then
        for d in "$tmpdir"/chromedp-runner.* "$tmpdir"/.com.google.Chrome.*; do
            [ -d "$d" ] && rm -rf "$d" 2>/dev/null || true
        done
    fi
done

# 验证端口
if command -v lsof >/dev/null 2>&1; then
    bridge=$(lsof -i :9333 2>/dev/null | grep -v COMMAND | head -1 || true)
    mcp=$(lsof -i :18060 2>/dev/null | grep -v COMMAND | head -1 || true)

    if [ -n "$bridge" ]; then
        echo "  ⚠️ 9333 端口仍被占用："
        echo "     $bridge"
    else
        echo "  ✅ 9333 端口（bridge_server）已释放"
    fi

    if [ -n "$mcp" ]; then
        echo "  ⚠️ 18060 端口仍被占用："
        echo "     $mcp"
    fi
fi

if [ "$found_any" = "0" ]; then
    echo "  ℹ️ 未发现任何 xhs 相关进程（可能本来就没跑）"
fi

echo "完成。"
