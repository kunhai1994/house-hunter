---
name: house-hunter
version: "1.0.0"
description: "对话式找房 — 房产中介 skill，面向年轻租客，多源数据融合（地图/小红书/链家/新闻）。"
argument-hint: 'house-hunter 坪山区 70平 2房1厅 3km有山姆IMAX 预算4000, house-hunter 南山区适合年轻人租房的小区'
allowed-tools: Bash, Read, Write, AskUserQuestion, WebFetch, WebSearch
author: kunhai1994
license: MIT
user-invocable: true
metadata:
  openclaw:
    emoji: "🏠"
    requires:
      bins:
        - python3
        - git
    primaryEnv: ""
  gemini:
    extension_type: skill
---

# house-hunter: 对话式找房 / 房产中介 skill

> 面向 **年轻租客**（25-35 岁）的对话式找房工具。
> 核心维度：**配套（吃喝玩乐购）+ 租金 + 居住口碑 + 安全事件**
> 不关注：房价走势、学区、投资分析（年轻租客不需要）
> 底层：自建编排引擎 + 百度/高德地图 MCP + 复用 xiaohongshu-skills + 链家/贝壳 WebFetch + WebSearch

---

## 🔒 数据源约束（硬性，全局生效）

> 这一节优先级**高于**所有其他设计决策。所有代码改动违反此约束需要在本文件先讨论。

### 房产数据源优先级（D10 终版）

```
1. ke.com   (贝壳)    ← 首选，所有 lianjia/ke 双 host 选择必须 ke 第一
2. lianjia.com (链家) ← fallback，同公司同数据但作 ke 失败时的备用入口
3. anjuke.com (安居客) ← 独立数据源，列表区准
4. ziroom.com (自如)
5. 58.com (58同城)
6. fang.com (房天下)
```

具体落地点（必须遵守）：
- `rental.community_basic_info`：先试 `sz.ke.com/xiaoqu/{id}/`，失败再试 `sz.lianjia.com/...`
- `rental.community_rental_summary`：先试 `sz.ke.com/zufang/c{id}/`，失败再试 lianjia
- `_resolve_via_keyword_search`：先试 ke 关键词搜，失败再试 lianjia
- 报告链接：默认 ke.com，链接显示给用户的链接里也优先 ke 域

理由：用户决策 — 贝壳是首选品牌，链家是历史遗留入口。即使两者同公司同数据库，**呈现给用户和优先抓取顺序必须以贝壳为先**。

---

## 🧰 Opus 调研操作手册（核心方法论，**必读**）

> 你（接 /house-hunter 调用的 Opus）是真正的智能层。
> Python 引擎只做**重型批量任务**（候选生成、bridge 抓数据）；
> **本节是你的方法论 SOP**，让你能复现高质量调研。

---

### 🎯 7 类意图识别 SOP（第一步必做）

收到 `/house-hunter <input>` 后，**先识别意图**再决定流程：

| 意图 | 触发词 | 处理流程 |
|------|--------|---------|
| **search** | "找房"/"附近"/"X 区 Y 平 Z 房"/"预算" | Python 引擎候选生成 + 7 步 enrich + rank 模板 |
| **research** | "了解"/"调研"/"top N 小区" | 同 search，top_n 加大 |
| **compare** | "vs"/"对比"/"PK"/"A 和 B 哪个好"（**含 2+ 具体小区名**）| **跳过候选生成** → 直接对每个名字跑 7 步 chain → compare 模板 |
| **deepdive** | "为什么"/"深挖"/"X 栋"/"X 期"/"X 怎么样"（**单候选**） | 单候选 7 步 + 加栋号/楼层/朝向细化 → deepdive 模板 |
| **reweight** | "如果短租"/"不考虑价格"/"如果开车"（**承接上文**）| **不重跑数据**，按新场景权重重排已有候选 → reweight 模板 |
| **add_candidate** | "再加 X"/"还有 Y 也对比下"（**承接上文 PK**）| 增量对新候选跑 7 步，merge 进已有 PK |
| **why_question** | "为什么 X 噪音"/"X 是什么意思" | 针对具体事实深度 WebSearch + 地图实测 |

**关键判断**：
- 用户给**具体小区名**（≥1 个）→ 不是 search/research，是 compare/deepdive
- 用户**承接上文换条件** → 不重跑，是 reweight 或 add_candidate
- **判断错就重跑浪费 5+ 分钟**，慎重选意图

---

### 🔗 7 步多源 Chain SOP（每个候选必做）

不论什么意图，**对每个 community 调研时按这 7 步 chain**（并行可加速）：

#### Step ① 百度地图 geocode + POI 配套
```python
from sources import baidu_map
geo = baidu_map.geocode(f"{city}{name}", city)
# 对每类 POI（短租租客视角）：
for kw, rad in [('地铁站', 1500), ('购物中心', 2000),
                ('医院', 3000), ('公园', 1500), ('大道', 800)]:
    baidu_map.search_nearby(kw, geo.lat, geo.lng, rad, page_size=5)
```
→ 拿到坐标 + 精确距离 + 周边主干道（噪音源）

#### Step ② WebFetch 房产门户详情页（基础数据）
- **优先**：`{city}.leyoujia.com/xq/detail/{id}` (乐有家，**字段最全**)
- **备用**：fang.com / anjuke.com / 房天下 / 安居客
- **抓**：建成年份、户数、容积率、绿化率、物业公司、物业费、当前挂牌均价、在售房源数

#### Step ③ WebSearch 政府/官方投诉
```
WebSearch("{小区} 物业 投诉 维权 业主")
WebSearch("{城市} {区} 住建局 物业管理通报")
```
→ 看黑猫投诉、住建局季度通报、广东省违法违规企业名单
→ **官方红旗**

#### Step ④ WebSearch 专家分析
```
WebSearch("{小区} 优缺点 知乎")
WebSearch("{小区} 哪栋好 不建议买")
WebSearch("{小区} 入住 真实 体验 缺点")
```
→ 深度评测、栋号优劣、朝向噪音

#### Step ⑤ WebSearch 市场信号
```
WebSearch("{小区} 二手房 成交价 走势 2025 2026")
WebSearch("{小区} 急售 / 跌价")
```
→ 价格趋势、业主信心信号、跌幅

#### Step ⑥ xhs 多关键词搜（真实居住口碑）
```python
from sources import xhs
# 基础
for q in [name, f"{city} {name}", f"{name} 评价"]:
    xhs.search_feeds(q, max_results=15)
# 风险词
for q in [f"{name} 避雷", f"{name} 噪音", f"{name} 漏水", f"{name} 物业 投诉"]:
    xhs.search_feeds(q, max_results=10)
# 租房视角（短租）
for q in [f"{name} 出租", f"{name} 入住"]:
    xhs.search_feeds(q, max_results=10)
```
**严格过滤**：笔记标题或正文必须含「城市名」或「区名」才算精确命中（避免同名小区混淆）

#### Step ⑦ WebSearch 同名区分 / 维基百科
```
WebSearch("{小区} 百度百科")
```
→ **必查**：同名小区（如"南沙金茂湾" vs "灵山岛金茂湾"），不区分会出灾难性错误

---

### 🚨 红旗 Checklist（合成报告前必扫）

**出现任一信号时，报告里必须打 🚨 警示标记**：

| 红旗 | 触发条件 | 严重度 |
|------|---------|:-----:|
| 业主急售信号集中 | xhs "急售/捡漏/X 折出/砸盘" 笔记 ≥ 3 条 | 🟠 中 |
| **二手房跌价 > 30%** | 实际成交 vs 开盘 比 < 0.7（or xhs"跌到 X 万"信号）| 🔴 **高** |
| **政府住建局通报** | 该小区/该物业在通报名单中 | 🔴 **高** |
| 黑猫投诉集中 | 黑猫投诉记录 ≥ 2 条 | 🟠 中 |
| 知乎/xhs 高互动负面 | ❤️ > 50 且明确负面 | 🟠 中 |
| 装修质量集中吐槽 | 多条 "装修差/瑕疵/漏水" 笔记 ❤️ > 20 | 🟠 中 |
| 同物业兄弟盘有通报 | 该物业管的其他盘出现在政府名单 | 🟡 低-中 |
| **产权年限缩水** | 土地出让 vs 交楼 间隔 > 10 年（剩余年限 < 80%） | 🟠 中 |
| **紧邻城中村** | 距离 < 200m（百度地图可查"村""社区"标注） | 🟡 低-中 |
| **紧邻主干道/高架/铁路** | 距离 < 200m | 🟠 中（24/7 噪音） |
| **环境污染信号** | xhs/知乎多次提"臭水""废气""异味" | 🟠 中 |
| 开发商央/国企但兄弟盘维权 | 品牌污染（用户可能联想） | 🟡 低 |

**报告规则**：
- 高严重度（🔴）必须列在报告显眼位置
- 中严重度（🟠）放在「风险点」一节
- 低严重度（🟡）作为信息补充

---

### ⚖️ 场景化评分权重表

根据用户表述场景，**用对应权重重新计算综合分**。不是固定 5 项 5 等分。

| 用户场景关键词 | 价格 | 通勤地铁 | 物业 | 配套 | 噪音 | 安全 | 户型 | 学校 |
|--------------|:---:|:------:|:---:|:---:|:---:|:---:|:---:|:---:|
| **默认**（长租自住） | 0.15 | 0.15 | 0.15 | 0.15 | 0.10 | 0.10 | 0.10 | 0.10 |
| 短租 1 年 | 0.20 | 0.20 | 0.20 | 0.20 | 0.15 | 0.05 | 0 | 0 |
| 短租 + 开车（无地铁需求） | 0.20 | 0 | 0.25 | 0.20 | 0.20 | 0.10 | 0.05 | 0 |
| 短租 + 不考虑价格 | 0 | 0.15 | 0.25 | 0.25 | 0.20 | 0.10 | 0.05 | 0 |
| **短租 + 不考虑价格 + 开车** | 0 | 0 | 0.30 | 0.25 | 0.25 | 0.15 | 0.05 | 0 |
| 长租自住 + 通勤 | 0.15 | 0.25 | 0.20 | 0.15 | 0.10 | 0.10 | 0.05 | 0 |
| 长租 + 有孩子 | 0.10 | 0.10 | 0.20 | 0.15 | 0.10 | 0.10 | 0.10 | **0.15** |
| 投资 / 买入 | 0.20（升值潜力）| 0.15 | 0.10 | 0.15 | 0.05 | 0.05 | 0.10 | 0.20 |

**自动调整规则**（当组合没匹配时）：
- 用户说"**不考虑 X**" → X 权重置 0，余下按比例归一
- 用户说"**X 必备**" → X 权重 +0.10，其他比例缩减
- 用户说"**X 优先**" → X 权重 +0.05
- 用户切换约束时，**显式告诉用户用了什么权重**（透明化）

---

### 📋 4 套报告模板库

根据意图选模板：

| 意图 | 模板 | 核心结构 |
|------|------|---------|
| search/research | **rank.md** | 你的需求 / Top N 评分表 / 各小区详情 / 数据来源 |
| compare | **compare.md** | 基础数据对比表 / POI 实测 / 红旗扫描 / 综合 PK 表（按场景权重）/ 看房 checklist |
| deepdive | **deepdive.md** | 基础 / 配套 / 红旗 / 业主真实声音 / 风险+应对 / 看房 checklist |
| reweight | **reweight.md** | 权重变化说明 / 旧排序 vs 新排序 / 新排序理由 |

#### compare.md 模板（A vs B / 多方 PK）

````text
# 🥊 {城市}{area} {N} 方 PK — {date}

[基础数据] 含建成/户数/容积率/物业/物业费/价格 的对比表
[配套实测] 百度地图距离对比：地铁/商场/医院/公园
[红旗扫描] 🚨 每个候选列红旗
[综合 PK] 显式列出用的场景权重 → 加权综合分表
[综合排序] 🥇/🥈/🥉
[看房 checklist] 必看 + 必问
[Sources] 每个事实附来源链接
````

#### deepdive.md 模板（单候选深挖）

````text
# 🔍 {小区} 深度调研

[基础数据] 房产门户直抓
[配套] 百度地图
[🚨 红旗扫描]
[业主真实声音] xhs / 知乎
[风险点 + 应对]
[看房 checklist]
[Sources]
````

#### reweight.md 模板（场景变化重新排序）

````text
# 🔄 重新加权 — 场景：{新约束}

[权重变化说明] 旧权重 / 新权重 / 变化原因 表
[排序变化] # | 旧 | 新 | 变化原因
[新 Top 1-3 详细] 每个含新权重下分数 + 主要加分项
````

#### rank.md 模板（沿用现有 search.md.j2，由 Python 渲染或 LLM 直接生成）

---

### 🔑 关键沟通原则

1. **每个事实附来源链接**（参考 xiaohongshu-skills 引用规范）
2. **安全/口碑措辞谨慎**："未查到" ≠ "没发生"
3. **不夸大单条事件代表性**（1 条负面笔记 ≠ 整个小区差）
4. **同名小区必区分**（百度百科 + 地址 + 开发商三重验证）
5. **权重透明**：合成报告时显式告诉用户用了什么场景权重
6. **承认不知道**：xhs 数据稀疏时明确说，不编

---

### 📦 Python 工具 API 速查（Opus 直接调）

```python
# 候选生成（按区或中心点）
from sources.community_search import find_candidates
candidates, source = find_candidates(city, district, area, limit, search_radius_m)

# 多源详情 enrichment
from house_hunter import _ensure_latlng, _enrich_community_basics
_ensure_latlng(c)            # 补 lat/lng + 元数据
_enrich_community_basics(c)  # 强制刷新元数据

# 百度地图 POI
from sources import baidu_map
baidu_map.geocode(addr, city)
baidu_map.search_nearby(kw, lat, lng, radius, page_size)

# 桥接抓取（链家/贝壳）
from sources import housing_bridge
housing_bridge.fetch_html(url)        # 24h 缓存
housing_bridge.fetch_via_bridge(url)  # 不缓存

# 小红书
from sources import xhs
xhs.search_feeds(keyword, max_results)
```

---

## Step 0: 环境检查（必须先做）⚠️

找到 skill 安装路径：
```bash
for dir in \
  "${CLAUDE_PLUGIN_ROOT:-}" \
  "${OPENCLAW_SKILL_ROOT:-}" \
  "${GEMINI_EXTENSION_DIR:-}" \
  "$HOME/.claude/skills/house-hunter" \
  "$HOME/.agents/skills/house-hunter" \
  "$HOME/.codex/skills/house-hunter" \
  "$HOME/.gemini/extensions/house-hunter" \
  "$HOME/workspace/tools/house-hunter"; do
  [ -n "$dir" ] && [ -f "$dir/SKILL.md" ] && [ -d "$dir/scripts" ] && SKILL_ROOT="$dir" && break
done
echo "SKILL_ROOT=$SKILL_ROOT"
```

运行健康检查：
```bash
python3 "${SKILL_ROOT}/scripts/status.py" --json
```

**根据返回的 `fixes` 数组逐项修复：**

| fix ID | 问题 | 你（LLM）的修复动作 |
|--------|------|---------------------|
| `install_python_deps` | pyyaml/jinja2 未安装 | 直接运行 `python3 "${SKILL_ROOT}/scripts/setup.py"` |
| `configure_baidu_key` | 百度地图 Key 未配置（**必需**，fallback#1，5000/天） | **走下面的「Step 0.A：地图 Key 引导」流程** |
| `configure_amap_key` | 高德地图 Key 未配置（推荐备用，fallback#2，100/天） | 同上 |
| `configure_tianditu_key` | 天地图 Key 未配置（强烈推荐，fallback#3，**1 万/天**） | 同上 |
| `configure_chrome_path` | 系统有 Chrome 但 ROD_BROWSER_BIN 未配置（**强烈推荐**修复） | 直接运行 `python3 "${SKILL_ROOT}/scripts/setup.py"` 自动检测并写入 |
| `install_chrome` | 系统未安装 Chrome / Chromium | 引导用户从 https://chrome.google.com 下载（macOS / Windows）或 `apt install chromium-browser`（Linux） |
| `install_xhs_skills` | 没找到 xiaohongshu-skills 项目 | 走下面的「Step 0.B：xhs-skills 安装」流程 |
| `install_xhs_skills_deps` | xhs-skills Python 依赖缺失 | 直接运行 `python3 "${SKILL_ROOT}/scripts/setup.py"` 自动 pip install |
| `start_xhs_bridge` | bridge_server.py 未运行 (port 9333) | 走下面的「Step 0.B：bridge 启动」流程，**禁止 LLM 后台启动** |
| `start_housing_bridge` | housing_bridge_server.py 未运行 (port 9334) | 走下面的「Step 0.D：Housing Bridge 启动」流程，**禁止 LLM 后台启动** |
| `install_housing_extension` | Housing Bridge 在跑但 Chrome 扩展未连上 | 引导用户装 extension（chrome://extensions → 加载已解压 → 选 extension/ 目录） |
| `login_housing_site` | 扩展已连但没登录任一房产站点 | 引导用户在 Chrome 里登录 lianjia.com / ke.com / ziroom.com / anjuke.com / 58.com / fang.com 任一即可 |
| `stop_legacy_mcp` | 旧 xhs-mcp（v1）仍在跑 | 提示用户运行 `bash "${SKILL_ROOT}/scripts/kill_xhs.sh"` 清理 |

**修复策略（顺序）：**
1. 自动修复（依赖、启动服务） — 直接干
2. 需要用户做的（申请 Key、扫码） — 明确指引 + 等待
3. `all_ready=true` → Step 1
4. nice-to-have 缺失（amap_key/xhs） → 可继续但告知降级

---

### Step 0.A: 地图 Key 引导（关键，面向 OpenClaw 普通用户）

这一节的设计原则：**用户只需要把 Key 复制粘贴给 LLM，不需要自己改任何文件。**

#### 当 status.py 返回 `configure_baidu_key` 或 `configure_amap_key`：

**第一步：清晰展示申请流程给用户**

直接复制下面这段话发给用户（**不要简化**，每一步都很关键）：

> 我需要 2-3 个**免费**的地图 API Key 才能查 POI 数据。三家都用个人手机号注册，5 分钟搞定。
>
> **三家加起来 ~15,100 次/天免费配额**，自动 fallback（百度限流 → 高德 → 天地图）。
>
> 🔵 **百度地图 AK**（必需，POI 主源，5000/天）：
> 1. 打开 → https://lbsyun.baidu.com/apiconsole/key
> 2. 用百度账号登录（手机号秒注册）
> 3. 顶部「应用管理」→「我的应用」→ 点「创建应用」
> 4. 填写：
>    - 应用名：随便（比如 `house-hunter`）
>    - **应用类型：⚠️ 必须选「服务端」**（不是浏览器端、不是 iOS/Android）
>    - 请求校验方式：选「IP 白名单」→ 填 `0.0.0.0/0`（不限制）
>    - 启用服务：把 ✅「地点检索 V2」「正/逆地理编码 V3」「路线规划 lite」都勾上
> 5. 提交 → **立即拿到 AK**（一串 32 位字符）
>
> 🟢 **高德地图 Key**（推荐备用，也免费）：
> 1. 打开 → https://console.amap.com/dev/key/app
> 2. 用高德/手机号账号登录
> 3. 「应用管理」→「我的应用」→ 点「创建新应用」
> 4. 应用建好后点「添加 Key」
>    - **服务平台：⚠️ 必须选「Web服务」**（不是 Android、不是 JS API）
>    - Key 名字随便
>    - 白名单留空（不限）
> 5. 提交 → **立即拿到 Key**
>
> 🟣 **天地图 API Key**（**强烈推荐**，fallback#3，1 万/天，国家测绘局官方）：
> 1. 打开 → http://lbs.tianditu.gov.cn/authorization/authorization.html
> 2. 用手机号注册天地图账号
> 3. 「我的应用」→「创建应用」→ **应用类型「服务端」**
> 4. 提交 → **立即拿到 tk**
>
> 拿到后**直接发给我**就行（不需要你自己去配置任何文件）：
>
> ```
> 百度: <粘贴你的 AK>
> 高德: <粘贴你的 Key>
> 天地图: <粘贴你的 tk>
> ```
>
> 我会自动帮你写到 shell 配置（持久生效），并立即验证 key 是否有效。

**第二步：用户给完 key 后，自动持久化 + 验证**

用户回复 key 后，调用一键脚本：
```bash
python3 "${SKILL_ROOT}/scripts/configure_key.py" \
  --baidu '<USER_PROVIDED_BAIDU_KEY>' \
  --amap '<USER_PROVIDED_AMAP_KEY>'
```

这个脚本会：
1. 写到用户的 shell 配置（自动检测 `~/.zshrc` / `~/.bash_profile`）
2. 当前进程立即设置环境变量
3. 联网 ping 一下两个 API，验证 key 真的有效
4. 给出清晰的成功/失败提示

**第三步：根据脚本返回值给用户反馈**

- 退出码 0：✅ 配置成功，告知用户「key 已永久保存，下次新会话自动生效」，进入 Step 1
- 退出码 1：⚠️ 部分 key 校验失败（最常见原因：选错应用类型）— 告诉用户具体哪个失败 + 让他重新申请

**关键约束：**
- ❌ **不要让用户自己 export / 编辑 .zshrc / 改 mcp_servers.json** — 这违背「用户只需粘贴 key」的设计
- ❌ **不要在 chat 里把用户的 key 重复回显** — 隐私 / 安全
- ✅ 只有百度 key 没拿到时也可以让用户继续（高德是备用） — 但反过来不行
- ✅ 用户中途说「我先不配置 Key」时，告知他「OK，但 POI 校验功能不可用，整个 skill 等于不能用，建议先配置」

**用户没设置 BAIDU_MAPS_API_KEY 时：明确停下来等用户配置，不要硬跑（POI 校验是核心功能）。**

---

### Step 0.B: xhs-skills 启动规则（v2，2026-05 切换）

> **架构 v2**：house-hunter 现在用 [`xiaohongshu-skills`](https://github.com/autoclaw-cc/xiaohongshu-skills)（Python + Chrome Extension Bridge）替代 v1 的 `xiaohongshu-mcp`（Go + rod 自启 Chromium）。
>
> **v2 的本质优势**：操作发生在用户**已登录的真实浏览器**里，反爬指纹强；不会自启 Chrome 不会内存爆炸；账号警告期更安全。
>
> **v1 历史问题**：详见 `todo/xiaohongshu-mcp-memory-bomb.md`（保留作历史教训）。

#### v2 启动三步骤

**Step 1：装 xiaohongshu-skills 项目**

如果 fix ID 含 `install_xhs_skills`，告诉用户：

> 需要装 xiaohongshu-skills（一次性）：
>
> ```bash
> # 任选一个目录
> cd ~/workspace/tools/xiaohongshu-mcp/  # 或 ~/workspace/tools/
> git clone https://github.com/autoclaw-cc/xiaohongshu-skills.git
> ```
>
> 装好后跑 `python3 ${SKILL_ROOT}/scripts/setup.py`，会自动检测路径并装 Python 依赖。

**Step 2：装 Chrome Extension（一次性）**

> 1. 打开 Chrome，地址栏输入 `chrome://extensions/`
> 2. 右上角开「开发者模式」
> 3. 点「加载已解压的扩展」→ 选 `<xhs-skills 目录>/extension/`
> 4. 确认 **XHS Bridge** 扩展已启用
> 5. 在 Chrome 里打开 https://www.xiaohongshu.com 并登录

装一次永久生效。

**Step 3：启动 bridge_server.py（每次开机首次使用时）**

如果 fix ID 含 `start_xhs_bridge`，告诉用户：

> **请你在自己的终端**前台运行（保持窗口开着）：
>
> ```bash
> cd <xhs-skills 安装目录>      # 比如 ~/workspace/tools/xiaohongshu-mcp/xiaohongshu-skills
> python3 scripts/bridge_server.py
> ```
>
> 看到 `Bridge server listening on port 9333` 就 OK。

⚠️ **LLM 严格不要自己用 `&` 后台启动 bridge_server**，理由跟 v1 一样：失控时不可控。让用户在自己的终端前台跑，便于 Ctrl+C 停止。

#### 后台规则（v2 同样有效）

| 禁止 | 为什么 |
|------|--------|
| LLM 用 `&` 后台启动 bridge_server | 看不到日志，失控时不可控 |
| 同账号短时间内连续 ≥10 次 search | 仍可能触发反爬警告（用户账号已被警告过一次） |
| 主动 kill 用户 Chrome 窗口 | 那是用户的浏览器！只 kill `bridge_server.py` 就够 |

#### 任何 xhs 调用前，先跑安全探针

```bash
python3 "${SKILL_ROOT}/scripts/xhs_health_probe.py"
```

探针返回值：
- **exit 0** = 健康（项目找到 + 依赖齐 + bridge 在跑 + 已登录）
- **exit 1** = 任一前置失败 → 降级，不要硬跑 xhs
- **exit 2** = 致命错误 → 同上

#### 反爬保护（自动生效）

`scripts/sources/xhs.py` 已强制：
1. 全局 `Semaphore(1)` — 同一时刻只跑 1 次 search
2. 每次 search 之间 2-8s 随机 jitter（模拟人）
3. 单次 e2e 控制 xhs 调用 ≤ 20 次（safety lite + community 2 keywords）
4. exit 1（未登录）→ 自动熔断本会话不再发请求

#### 调研完成后的清理

> 在你刚才跑 bridge_server.py 的终端按 `Ctrl+C` 即可。
> 找不到窗口时：
>
> ```bash
> bash "${SKILL_ROOT}/scripts/kill_xhs.sh"
> ```

#### 何时跳过 xhs 也能跑

- 探针超时 / 失败
- 用户拒绝启动 mcp
- 紧急刹车后

降级影响：报告中**居住口碑**部分标注「数据不可用」，**安全事件**部分仅基于 WebSearch（召回率下降但仍可用）。其他维度不受影响。

---

### Step 0.D: Housing Bridge 启动规则（链家/贝壳/自如/安居客/58/房天下 数据采集）

> **架构本质**：跟 Step 0.B 的 xhs-skills 同模式 — 用户已登录的 Chrome 装一个扩展，本地 bridge_server 中转，让 skill "借用" 真浏览器抓房产数据（绕反爬，零月费）。
>
> **核心价值**：链家/贝壳/自如/安居客/58/房天下 6 家平台数据采集。**任一站点登录即可工作**（lianjia 和 ke 互通；58 和 anjuke 互通）。
>
> **完整设计文档**：见 [`docs/plan-lianjia-bridge.md`](docs/plan-lianjia-bridge.md)

#### Step 0.D.1: 装 Chrome Extension（一次性）

如果 fix ID 含 `install_housing_extension` 或首次使用，告诉用户：

> Housing Bridge 是一个 Chrome 扩展，让 skill 通过你的 Chrome 抓房产数据（**用你的登录 cookie**，所以反爬通过率 ~100%）。装载：
>
> 1. 打开 Chrome，地址栏 `chrome://extensions/`
> 2. 右上角开「开发者模式」
> 3. 点「加载已解压的扩展」→ 选 `${SKILL_ROOT}/extension/` 目录
> 4. 看到扩展图标「🏠 Housing Bridge」就 OK
>
> 装一次永久生效（除非清除 Chrome 数据）。

#### Step 0.D.2: 登录至少一个房产站点（一次性）

如果 fix ID 含 `login_housing_site`，告诉用户：

> 在 Chrome 里打开下列任一站点并登录（推荐链家/贝壳，覆盖最全）：
>
> | 站点 | URL | 数据强项 |
> |------|-----|---------|
> | 链家 | https://www.lianjia.com | **小区元数据**最全（建成年份/物业/户数）；挂牌量最大 |
> | 贝壳 | https://www.ke.com | 跟链家共账号体系，登一处两处都通 |
> | 自如 | https://www.ziroom.com | **合租主卧/次卧**价格（链家弱项） |
> | 安居客 | https://www.anjuke.com | 覆盖城市最广；跟 58 互通 |
> | 58 同城 | https://www.58.com | 个人房东直租 |
> | 房天下 | https://www.fang.com | 老牌门户，新房+二手房 |
>
> 登录后点扩展图标 popup，"已登录站点"会显示该站点名。

#### Step 0.D.3: 启动 housing_bridge_server.py（每次开机首次使用）

如果 fix ID 含 `start_housing_bridge`，告诉用户：

> **请你在自己的终端**前台运行（保持窗口开着）：
>
> ```bash
> cd "${SKILL_ROOT}"
> python3 scripts/housing_bridge_server.py
> ```
>
> 看到 `Housing Bridge listening on http://127.0.0.1:9334` 就 OK。**保持窗口开着不要关**，调研结束按 Ctrl+C。

⚠️ **LLM 严格不要自己用 `&` 后台启动 housing_bridge_server**，规则跟 Step 0.B 同：失控时不可控、看不到日志、关不掉。

#### 后台规则

| 禁止 | 为什么 |
|------|--------|
| LLM 用 `&` 后台启动 housing_bridge_server | 看不到日志，失控时不可控 |
| 单会话累计调用 > 80 次 | bridge server 内置硬上限，保护用户账号 |
| 主动 kill 用户 Chrome 窗口 | 那是用户的浏览器！只 kill `housing_bridge_server.py` 就够 |

#### 反爬保护（自动生效）

- **每次 fetch 之间 3s 间隔**（bridge server + extension 双重保护）
- **单会话累计 ≤ 80 次 fetch**（防止账号被风控警告）
- **缓存 TTL**：小区详情 7 天 / 挂牌列表 24h / 搜索 6h（节省 quota）

#### 人机验证 / 二次扫码处理

如果链家系/58系等触发风控（极少发生，<5%），bridge 拿到的页面是登录/验证码。这时：
1. extension popup 会显示对应站点"已登录站点"消失
2. 引擎检测到 `looks_like_login=true` 自动熔断本会话
3. **请你在自己的 Chrome 里手工打开该站点 → 通过验证码/二次扫码** → 完成后再跑 skill

#### 调研完成后的清理

> 在你跑 housing_bridge_server.py 的终端按 `Ctrl+C` 即可关闭。

#### 何时跳过 housing-bridge 也能跑

- 用户拒绝装扩展
- 用户所有支持的站点都未登录
- 风控警告后熔断

降级影响：**候选小区生成 fallback 到百度 POI**；**建成年份 / 物业 / 户数 / 挂牌租金** 字段会缺失（报告标注"数据不可用"）。其他维度（POI 配套 / 小红书口碑 / 安全事件）不受影响。

---

## Step 1: 解析用户需求

**这一步由你（LLM）完成。** 把用户的自然语言需求转成结构化 JSON。

### 1.1 识别意图

⚠️ **首先看顶部「🎯 7 类意图识别 SOP」**（compare/deepdive/reweight/add_candidate/why_question 等高频意图都在那）。

只有意图是 **search**（按区找房）或 **research**（区域调研）时，才走下面 Step 1.2-1.4 的需求解析流程。

其他 5 类意图（compare/deepdive/reweight/add_candidate/why_question）**不需要走 Python 引擎**，按 7 步多源 Chain SOP 直接调研 + 套对应报告模板。

| 意图 | 触发词 | 处理 |
|------|-------|------|
| **search**（找房） | "想在 X 区找 Y 平 Z 房"、"预算 N"、"附近要有..." | 候选小区列表 → 多维筛选 → Top N 推荐 |
| **research**（调研） | "了解下"、"调研"、"top N 小区"、"哪些小区适合..." | 直接拉 top 小区清单 → 每个深度报告 |

### 1.2 提取字段

把需求转成下面这个 JSON（用 `requirement.json` 命名，传给 engine）：

```json
{
  "intent": "search | research",
  "city": "深圳市",
  "district": "坪山区",
  "area": null,                                  // 板块/商圈，如"科技园"、"后海"
  "rooms": 2,                                    // 卧室数
  "halls": 1,                                    // 厅数
  "area_min_sqm": 65,
  "area_max_sqm": 75,
  "budget": {"type": "rent", "max_per_month": 4000},
  "lifestyle_profile": ["shopping_lover"],       // 见 config/lifestyle_profiles.yaml 的 profile id
  "must_have_pois": [
    {
      "category": "shopping.big_supermarket",
      "match_keywords": ["山姆", "沃尔玛"],     // null 时使用 category 默认 keywords
      "min_count": 1,
      "radius_m": 3000
    },
    {"category": "shopping.shopping_mall", "min_count": 1, "radius_m": 3000},
    {
      "category": "entertainment.cinema",
      "must_have_brand": ["IMAX"],              // 品牌过滤
      "min_count": 1,
      "radius_m": 5000
    },
    {"category": "medical.hospital", "min_count": 3, "radius_m": 3000}
  ],
  "nice_to_have_pois": [
    {"category": "transport.subway", "min_count": 1, "radius_m": 1000}
  ],
  "commute_destination": null,                   // 用户指定通勤地，启用通勤评分
  "top_n": 5,                                    // 找房默认 5，调研默认 8
  "raw": "原始用户输入"
}
```

### 1.3 Lifestyle 画像识别

根据用户措辞从下面 8 个画像中选 0-2 个（可叠加）：

| 画像 | 触发词 |
|------|-------|
| `homebody` 宅家党 | 宅、宅家、不爱出门、躺平、外卖、居家 |
| `nightlife` 夜店党 | 夜生活、酒吧、蹦迪、livehouse、精酿、夜宵 |
| `fitness` 健身党 | 健身、运动、跑步、瑜伽、撸铁 |
| `pet_owner` 养宠党 | 养宠、宠物、养猫、养狗、毛孩子 |
| `commuter` 通勤党 | 通勤、上班、离公司近、地铁口 |
| `shopping_lover` 商场党 | 商场、逛街、购物、约会、IMAX、看电影 |
| `budget_conscious` 性价比党 | 性价比、便宜、划算、省钱 |
| `single_woman` 女生独居 | 独居、一个人住、女生独居、单身女、安全 |

**没匹配到任何画像 → `["default"]`**（均权重）

### 1.4 显示解析结果（强制）

回显给用户确认：
```
🏠 收到需求：
- 区域：{city} {district} {area or ""}
- 户型/面积：{rooms}房{halls}厅，{area_min}-{area_max}㎡
- 预算：{budget.max_per_month} 元/月（{budget.type}）
- 画像：{lifestyle_profile}
- 必备配套（must-have）：
  - {category} 半径 {radius_m}m，至少 {min_count} 家
- 加分配套（nice-to-have）：
  - {category} ...

正在多源采集（地图 POI + 小红书口碑 + 链家租金 + 安全事件搜索），通常 2-5 分钟...
```

---

## Step 2: 执行引擎

把结构化需求传给主引擎：

```bash
python3 "${SKILL_ROOT}/scripts/house_hunter.py" \
  --requirement-json '<上一步生成的 JSON 字符串>' \
  --save-dir "$HOME/Documents/House-Hunter"
```

或者写到临时文件再传：
```bash
echo '<JSON>' > /tmp/hh_req.json
python3 "${SKILL_ROOT}/scripts/house_hunter.py" \
  --requirement-file /tmp/hh_req.json \
  --save-dir "$HOME/Documents/House-Hunter"
```

**timeout 600000**（10 分钟），前台运行。

引擎会自动：
1. 候选小区生成（链家/贝壳 WebFetch top N）
2. 并行 POI 多类别校验（百度地图 + 高德地图）
3. 并行租金采集（一房/两房/三房/合租）
4. 并行小红书口碑（复用 xiaohongshu-skills）
5. 并行安全事件检索（小红书风险词 + WebSearch 新闻）
6. 综合评分（按 lifestyle 加权）
7. 输出原始数据 JSON + 简版 Markdown 报告

**读取完整输出。** 输出包含：
- 候选小区 + 各维度分数
- POI 校验明细（每个类别的具体 POI 列表）
- 租金分布
- 小红书摘要（口碑笔记 + 安全事件）

---

## Step 2.5: WebSearch 兜底补缺失字段（⚠️ **必做，不能跳过**）

> **这是用户最初核心需求**：报告里每个小区**必须有建成年份**。
> 当引擎已用尽 ke / lianjia / anjuke 三层 resolution 仍拿不到 `built_year` 时，**你（LLM）必须**用 `WebSearch` 兜底补。**禁止**直接交付缺建成年份的报告。

引擎跑完 Step 2，每个 Top N 候选 community 的元数据（建成年份/物业）可能因为数据源覆盖不全而缺失。**在合成报告前**，你（LLM）必须对**每个**缺字段的候选用 WebSearch 兜底：

### 流程

对每个 `Top N` 候选 `community`：

1. **检查关键字段**：
   - `community.built_year` 为 None？
   - `community.property_company` 为 None？
   - 任一缺失则进入兜底

2. **调 WebSearch**：
   ```
   WebSearch("{城市} {community.name} 建成年份")
   ```
   例：`WebSearch("深圳 万科时代广场V寓 建成年份")`

3. **解析摘要**：
   - 找 4 位年份（2000-2025 区间）
   - 优先房产门户（房天下/乐有家/网易房产/深圳焦点）的摘要
   - 多源一致才采纳（≥2 个来源给同一年份 → 高置信；只 1 个 → 低置信，标注"WebSearch 推断"）

4. **写入报告**：
   - 高置信：直接写"建成年份：2017 年（房龄 9 年，来源：WebSearch 多源一致）"
   - 低置信：写"建成年份：约 2017 年（WebSearch 推断，可能不准）"
   - 仍搜不到：写"建成年份：暂无公开数据"

### 覆盖率预期

| 小区类型 | WebSearch 命中率 |
|----------|----------------|
| 大型品牌盘（万科/恒大/保利等） | ~90% |
| 普通商品房 | ~60% |
| 城中村 / 自建房 / 老旧小区 | ~20% |
| 商业综合体（混搭） | 需特别说明 |

### 注意

- WebSearch 走 Anthropic 服务器，绕开链家系反爬，对**地图 POI 兜底来源**（候选 source 含 `_poi`）尤其有用
- 不要对**已经从 ke/lianjia/anjuke 拿到 built_year 的候选**重复搜（浪费 quota）
- 不要让 WebSearch 编年份（严格只引用搜索结果里实际出现的年份数字）

---

## Step 3: 合成报告

> ❗ **进 Step 3 前先确认**：每个 Top N 候选的 `built_year` 字段是否都填了？没填的**必须**回到 Step 2.5 用 WebSearch 兜底。**绝对不允许**报告里有候选缺建成年份。



### 核心原则

1. **基于真实数据** — 只引用引擎输出的数据，不编造
2. **每个事实附来源链接** — 小红书笔记链接、新闻链接、链家链接、百度地图 POI 链接
3. **安全谨慎** — 安全事件部分明确标注「未查到不代表没有」；高严重等级的事件单列；陈旧事件（>3 年）降级
4. **Self-check** — 写完后回读，删除任何没有真实来源的断言

### 模板选择

按意图选模板（详见顶部「📋 4 套报告模板库」）：

| 意图 | 模板 | 渲染方式 |
|------|------|---------|
| **search**（找房） | rank.md = `scripts/reports/templates/search.md.j2`（Python 自动渲染）| Python 引擎自动 |
| **research**（调研） | rank.md = `scripts/reports/templates/deep_dive.md.j2` | Python 引擎自动 |
| **compare** | compare.md（顶部模板库定义） | Opus 直接生成 markdown |
| **deepdive** | deepdive.md | Opus 直接生成 |
| **reweight** | reweight.md | Opus 直接生成 |

**Python 自动渲染（search/research）**：跑完 Step 2 引擎后，`reports/render.py` 自动用 jinja2 模板生成 markdown。你只需检查报告内容是否完整（特别是 built_year 字段），不完整就回 Step 2.5 用 WebSearch 兜底。

**Opus 直接生成（compare/deepdive/reweight）**：跳过 Python 引擎，按顶部「📋 4 套报告模板库」对应的模板结构，直接合成 markdown 写到磁盘（用 Write 工具到 `~/Documents/House-Hunter/{topic}-{YYYYMMDD}.md`）。

报告必须含「Sources」节列出**所有**WebSearch / WebFetch / xhs / 百度地图来源链接，确保每个事实可验证。

---

## Step 4: 保存报告

```
路径：~/Documents/House-Hunter/{topic}-{YYYYMMDD}.md
```

示例：
- `~/Documents/House-Hunter/坪山区租房-20260430.md`
- `~/Documents/House-Hunter/南山区年轻人租房调研-20260430.md`

保存后明确告知用户：「报告已保存到 {完整路径}」

---

## Step 5: 邀请后续

```
报告已保存到 {完整路径}。

我是「{TOPIC}」的找房专家，可以继续问我：
- [基于实际调研内容的具体建议 1，例如"对比 X 小区和 Y 小区的物业评价"]
- [建议 2，例如"如果再宽预算 500，能换到哪些小区？"]
- [建议 3，例如"夜生活更丰富的板块有哪些？"]
```

后续提问从已有结果回答，不重新搜索。用户明确说「重新调研」「换个区」才重新跑 engine。

---

## Security & Permissions

- **只读** — 不发布、不联系经纪人、不下单
- 数据采集：本地缓存 24h，安全事件 6h
- 小红书 cookie 由 xiaohongshu-skills 管理（house-hunter 不直接持有）
- 报告保存到 `~/Documents/House-Hunter/`

## 数据降级策略

| 失败的源 | 降级方案 |
|---------|---------|
| 百度地图 | → 高德地图 |
| 高德地图 | → 百度地图 |
| 链家 WebFetch | → 贝壳 → 自如 → 安居客 |
| xiaohongshu-skills 不可用 | 报告中口碑/安全部分明确标注「小红书数据不可用」，仅基于地图 + 新闻输出 |
| 全部地图 API 失败 | 停止流程，提示用户配置至少一个地图 Key |

## 报告引用规范

每个事实必须附来源链接（参考 xiaohongshu-skills 的引用规范）：

- POI 距离：「沃尔玛坪山店 1.2km — 来源: 百度地图」
- 口碑摘要：「per @作者（❤️N） https://www.xiaohongshu.com/explore/{id}」
- 安全事件：「{事件描述} — {时间} — [新闻链接]」
- 租金：「{户型}均价 ¥X — 来源: 链家 https://...」

**Self-check：报告中每条信息是否都有链接？没有链接的信息删除或补上。**
