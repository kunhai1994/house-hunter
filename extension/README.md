# Housing Bridge — Chrome Extension

让 house-hunter skill 通过你已登录的 Chrome 抓取链家/贝壳/自如/安居客/58/房天下数据。

## 装载步骤（一次性）

1. 打开 Chrome，地址栏输入 `chrome://extensions/`
2. 右上角开启「开发者模式」
3. 点「加载已解压的扩展」，选择本目录（`extension/`）
4. 装好后，扩展图标出现在工具栏；可点 popup 看状态

## 启动 bridge server（每次开机首次用时）

在 house-hunter 项目根目录的另一个终端：

```bash
cd ~/workspace/tools/house-hunter
python3 scripts/housing_bridge_server.py
```

看到 `Bridge server listening on :9334` 表示 OK。**保持窗口开着不要关**，结束时 Ctrl+C。

## 登录至少一个房产站点

在 Chrome 里打开下列任一站点并登录（推荐 lianjia/ke 链家系数据最全）：

- https://www.lianjia.com / https://www.ke.com
- https://www.ziroom.com（自如，合租主卧）
- https://www.anjuke.com（安居客）
- https://www.58.com（58 同城）
- https://www.fang.com（房天下）

登录后点扩展 popup，"已登录站点"会显示对应站点名。

## 工作原理简述

扩展只做一件事：在你已登录的 Chrome 里调 `fetch(url)`，把 HTML 回给本地 bridge_server。所有 cookie / TLS 指纹 / HTTP 协议栈都是真实 Chrome 的，目标站点反爬识别不出来。详见 [`../docs/plan-lianjia-bridge.md`](../docs/plan-lianjia-bridge.md) §2。

## 限速与合规

扩展强制每次 fetch 至少 2 秒间隔，配合 bridge_server 的 80 次/session 上限保护账号。**仅自用**，不要批量爬取转售。
