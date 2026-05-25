[English](README.md) | [中文](README.zh-CN.md)

# 🏠 house-hunter

自己找房子的时候，地图、贝壳/链家、小红书、黑猫、知乎挨个跳来跳去，实在难受。

写了这玩意儿给自己用。直接跟 **龙虾 / Claude Code / OpenClaw / Gemini CLI** 等 AI 对话就行，一句话告诉它要找啥，它去跑地图/贝壳/小红书/知乎/黑猫，10-15 分钟给你一份带链接的小区报告。

代码基本都是 AI 写的，按我意思来。

**放这里，有需要自取。**

---

> 粒度只到小区，不到具体房源（哪栋哪号、几室朝向那些）。
>
> 我自己的用法：用它圈定该看哪些小区，再去贝壳 APP 翻具体挂牌。选错小区比选错房源代价大得多。
>
> 报告里展示小区当前挂牌中位价作参考，不强制按预算筛除（同小区不同户型/楼层/装修差价能差不少，要严格按预算只能到房源级看挂牌）。

## 这玩意儿能干啥？

找房子常常要在多个平台来回跳：

| 想知道的事 | 没这玩意儿之前 | 用了之后 |
|---|---|---|
| 区域 + 户型 | 贝壳/链家 APP 筛 | 一句话 |
| 周边商场/影院/医院 | 地图 APP 一个个搜，画半径量距离 | 自动 |
| 业主真实评价 | 小红书翻几十条帖子 | 自动 |
| 物业 / 投诉 | 知乎 + 黑猫分别搜 | 自动 |
| 比较几个候选 | 自己列 Excel 对齐数据 | 自动多维对比表 |
| 哪个有坑（急售/跌价/通报）| 凭运气 | 12 个红旗信号自动扫 |
| 总耗时 | 几小时到几天 | 10-15 分钟 |

一句话把多个源串起来，出一份带链接的小区对比报告。每条结论都能点链接验证。

## 怎么装？

不会编程也能装，复制粘贴 + 完成几件本人才能做的事就行。

### 第一步：把下面这段粘贴到龙虾 / Claude Code / OpenClaw 对话框

````
帮我安装 house-hunter 房产调研 skill：

1. 从 GitHub 下载这个项目：https://github.com/kunhai1994/house-hunter
   （Claude Code 放 ~/.claude/skills/，OpenClaw / 龙虾 放 ~/.agents/skills/）

2. 同时下载它依赖的另一个项目：https://github.com/autoclaw-cc/xiaohongshu-skills
   （没它拿不到业主真实评价）

3. 装好两个项目的 Python 依赖

4. 读 house-hunter 里的 SKILL.md，重点看 Step 0 / 0.A / 0.B / 0.D，按里面写的去做

5. 你能自动做的就自己做完（下载、装依赖、写配置、起后台服务）
   遇到「必须用户亲自做」的就停下来一步步告诉我怎么操作：
   - 注册地图 API 账号（给我直达链接，我注册完粘贴 key 回来）
   - 装浏览器扩展（用文字告诉我点哪里、菜单叫什么）
   - 扫码登录贝壳和小红书（给我网址，我扫完告诉你）
   每次只让我做一件事

6. 全部装好告诉我重启对话，输入 /house-hunter "..." 开始用
````

发出去，AI 会自己跑下载、装依赖、写配置、起服务这些事。

### 第二步：必须本人做的 3 件事（不是 AI 偷懒，是安全原因）

| 必做项 | 为啥 |
|---|---|
| 注册 3 个地图 API 账号（百度地图 / 高德 / 天地图，全免费，加起来 1.5 万次/天） | 这些账号要实名手机号注册。AI 用别人身份注册违反平台规则、容易被封 |
| 浏览器装 2 个插件（一个抓贝壳/链家，一个抓小红书）| Chrome / Edge 禁止任何脚本自动装插件——浏览器对隐私的保护设计。AI 会一步步告诉你点哪里 |
| 手机扫码登录贝壳 + 小红书（各 1 秒）| 账号 = 你的身份。AI 不能代登录任何账号 |

### 第三步：装好后，新开一个对话

```
/house-hunter "你的问题"
```

## 为啥要装那俩依赖？

xhs-skills 和 Housing Bridge 不装也能跑，但：

- 拿不到贝壳/链家实时挂牌（只能从地图 POI 兜底）
- 没业主真实评价
- 红旗扫描没法工作

跟其他纯地图 agent 就没区别了。我自己不会这么用。

举个例子，问「南沙星河东悦湾怎么样」：

| 维度 | 不装 | 装了 |
|---|---|---|
| 价格 | "开盘 32000 元/㎡"（门户官方话术） | 二手房实际成交跌到 15500 元/㎡（贝壳数据）|
| 业主声音 | 无 | "❤️23/💬71 契税大坑" + "❤️18/💬42 收楼装修太差" 等真实吐槽 |
| 物业 | "星河智善（开发商旗下）" | 同物业兄弟盘 XX 在住建局通报名单 |

仓库链接：

- Housing Bridge：仓库自带 `extension/`，跟着 AI 装
- xiaohongshu-skills：[https://github.com/autoclaw-cc/xiaohongshu-skills](https://github.com/autoclaw-cc/xiaohongshu-skills)

## 装好咋用？

skill 自己识别意图。输出都是小区列表，不到具体房源。

### 找小区（多条件配套）

```
/house-hunter 光明区 90 平左右 3 房 1 厅，附近 3km 要有 IMAX 影院 + 山姆/沃尔玛 + 三家医院
```

### PK 对比

```
/house-hunter 越秀滨海御城 vs 滨海悦城 vs 星河东悦湾 哪个口碑好（不考虑学校）
```

### 深挖单个小区

```
/house-hunter 帮我调研中海寰宇时代花园
```

### 针对某栋的具体问题

```
/house-hunter 星河东悦湾 9/10/11 栋为什么噪音大
```

输出是问题分析报告，不是该栋房源列表。

### 中心点搜索（不限行政区）

```
/house-hunter 以光明凤凰城为中心，1km 内 2 房 1 厅
```

### 跑完接着追问

skill 不是一次性查询，承接上次报告做调整：

| 想做的事 | 直接说 |
|---|---|
| 换场景重排（不重跑数据） | "我只租 1 年 + 开车不要地铁，重新排" |
| 加候选 | "再加上灵山岛金茂湾" |
| 删候选 | "把 XX 去掉，剩下重排" |
| 追问结论 | "为什么 Top 1 的安全分只有 60" |
| 切硬约束 | "排除 2015 年以前建成的" |

## 报告长啥样？

存到 `~/Documents/House-Hunter/{话题}-{日期}.md`：

- 多维对比表（建成年份 / 物业 / 配套精确距离 / 综合分）
- 红旗扫描（急售/跌价/政府通报/装修吐槽/紧邻主干道 等 12 个信号）
- 业主真实声音（带 ❤️ + 评论数 + 小红书链接，每条可点开验证）
- 看房 checklist
- 每个事实附原始链接

## 底层咋跑的？

```
你: /house-hunter "你的问题"
  │
  ▼
SKILL.md（Opus 调研操作手册）
  │
  ├─ 识别意图（多条件搜 / PK / 深挖 / 中心点 / 对话式追问）
  │
  ▼
对每个小区，自动调 7 个数据源：
  ① 百度地图 POI（精确距离）
  ② 房产门户（贝壳/链家/安居客 抓基础数据）
  ③ 政府投诉（黑猫 / 住建局通报）
  ④ 知乎专家分析
  ⑤ 市场信号（成交价/急售）
  ⑥ 小红书业主口碑（含"避雷""噪音""漏水"风险词）
  ⑦ 同名小区区分（百度百科）
  │
  ▼
红旗扫描 + 场景化加权评分（短租/开车/有孩子 自动调权重）
  │
  ▼
~/Documents/House-Hunter/{话题}-{日期}.md
```

## 用着出问题了？

### 报告里小区不在我搜的区

链家 `/xiaoqu/longgang/` 列表自身就会混跨区。换中心点模式：

```
/house-hunter 以龙岗中心城为中心，1km 内 2 房 1 厅
```

百度地图 nearby 保证半径内必在该区。

### 报告缺建成年份

让 LLM 用 WebSearch 补：

```
帮我用 WebSearch 补全报告里缺的建成年份
```

### 链家/贝壳跳到登录页 / CAPTCHA

Chrome 手动打开报错的 URL（如 `https://sz.lianjia.com/xiaoqu/2123/`），过完验证回 LLM 继续。链家每个 path 当独立风控池，过了同 path 24h 不需再过。

### 小红书全返 0 结果

账号被风控。Chrome 手动打开 https://www.xiaohongshu.com/ 看是否提示「请求太频繁」。等 1-24 小时；期间临时禁用：

```
告诉 LLM 设 HOUSE_HUNTER_DISABLE_XHS=1 跑
```

其他维度照常工作，只是没业主口碑。

### bridge server 没启

```bash
cd ~/.claude/skills/house-hunter
python3 scripts/housing_bridge_server.py
```

看到 `Housing Bridge listening on http://127.0.0.1:9334` 就 OK。**保留窗口，Ctrl+C 结束。**

### 报告链接死了（`[name](#)`）

候选源走了百度 POI 兜底（贝壳/链家没匹配上）。让 LLM 补：

```
帮我用 WebSearch 给每个小区找贝壳/链家链接
```

更多见 [docs/FAQ.md](docs/FAQ.md)。

## 想改一下？

代码都在本地，要改让 LLM 改：

```
帮我把购物中心的默认搜索半径改成 2km
帮我加一个"养宠物"的 lifestyle 权重
帮我改成只搜带电梯的小区
```

## 数据来源

| 数据 | 来源 |
|---|---|
| POI 距离 / 配套 | 百度地图 / 高德 / 天地图 三层 fallback |
| 挂牌价 / 户数 / 物业 / 建成年份 | 贝壳 ke.com（首选）/ 链家 / 安居客（经 Housing Bridge 调你已登录浏览器）|
| 业主口碑 / 居住体验 | 小红书（你已登录账号，经 xiaohongshu-skills）|
| 政府投诉 / 通报 | 黑猫投诉 / 住建局公开数据 |
| 专家分析 / 二手价 | 知乎 / 乐有家 / 房天下（WebSearch）|
| 兜底建成年份 | 公开搜索引擎摘要 |

## 文件位置

| 文件 | 路径 |
|---|---|
| Skill（Claude Code）| `~/.claude/skills/house-hunter/` |
| Skill（OpenClaw / 龙虾）| `~/.agents/skills/house-hunter/` |
| 报告 | `~/Documents/House-Hunter/` |
| 缓存 | `~/.local/share/house-hunter/cache/` |
| Map API Keys | shell 配置（`~/.zshrc` 或 `~/.bash_profile`）|

## 系统要求

Python 3.9+ / Git / Google Chrome / macOS or Linux or Windows (WSL)。

## 详细文档

- [SKILL.md](SKILL.md) — Opus 调研方法论
- [docs/EXAMPLES.md](docs/EXAMPLES.md) — 10 个真实场景
- [docs/FAQ.md](docs/FAQ.md) — 24 常见问题
- [docs/plan-lianjia-bridge.md](docs/plan-lianjia-bridge.md) — Housing Bridge 设计
- [docs/data-sources.md](docs/data-sources.md) — 数据源详解

## 许可

MIT。

用着有意见 / 建议 / 觉得哪里坑，提 issue 告诉我。

## 致谢

- [xiaohongshu-skills](https://github.com/autoclaw-cc/xiaohongshu-skills) — 必备数据源（小红书业主口碑）
- 百度地图 / 高德 / 天地图 开放 API
