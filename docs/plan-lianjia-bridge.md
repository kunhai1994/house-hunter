# Plan: Housing Bridge — 浏览器扩展接管多个房产平台

> **作者**：Claude (Opus 4.7)
> **日期**：2026-05-11（v3，多站点架构 + Phase 划分）
> **关联**：[known-issues.md](./known-issues.md) P0-1（链家系全网络反爬）
> **本质**：通用浏览器扩展 + Python bridge，让 skill 通过用户已登录的 Chrome 抓多个房产平台数据
> **实施范围**（v4 修订）：lianjia + ke + ziroom + anjuke + 58 + fang **6 个站点一次性全做**
> **v3 → v4 关键变化**：原计划分 Phase 推进，用户决定今晚一次完成。Phase 标签留作"架构分组"（adapter 隔离原则），不再是时间分组。M1-M6 扩展为 M1-M9。账号由用户后续注册，先写代码后分批 e2e。
> **预计真实墙钟（Phase 1）**：单 session 3-5 小时（顺利）/ 5-7 小时（含调试）

---

## 0. TL;DR

写一个 Chrome Extension + Python bridge server，让 house-hunter 通过**用户已登录的 Chrome** 抓多家房产平台。

**为什么不直接 Python requests**：链家系反爬看 TLS 指纹 + HttpOnly cookie + 动态签名，Python 模拟不出来。详见 §2。

**为什么分 Phase**：单 session 做 5 个站点会卡在"哪个 HTML 解析先 ready"。Phase 1 先 lianjia + ke（同公司同模板，几乎零额外成本），架构预留多站点适配器，后续按需扩。

---

## 1. 目标与验收标准

### 目标（Phase 1）
让 house-hunter 在「用户网络环境对链家系全反爬」的现状下，仍能拿到：
- **小区信息**：建成年份、楼栋数、户数、物业公司
- **房间信息**：在售/在租户型、面积、楼层、朝向、装修
- **价格信息**：挂牌价分布（一房/两房/三房/合租）、历史成交价

### 验收标准（Phase 1 必达）
- [ ] 重跑龙岗用例，候选来源是 `lianjia_full` 或 `ke_full` 不是 `baidu_map_poi`
- [ ] 报告 Top 5 每个小区都显示**建成年份**
- [ ] 报告租金维度不再全 50 分，预算 5000 能筛掉超预算小区
- [ ] 整套机制走用户已登录 Chrome（lianjia 或 ke 任一）
- [ ] e2e 总耗时 < 15 分钟

### 验收标准（架构必达，为 Phase 2/3 准备）
- [ ] 加新站点 = 加一个 `site_adapters/<site>.py` + manifest 加一个 host_permissions，**不动核心代码**
- [ ] 数据 schema 统一（`CommunityInfo` / `Listing` / `PriceInfo` 三个数据类）
- [ ] 站点失败时自动 fallback 到下一站点（多源冗余）

---

## 2. 工作原理（必读）

### 2.1 Chrome Extension 在我们场景里**干什么**

**只干一件事**：在 Chrome 内调 `fetch(url)`，把 HTML 回传给 skill。

**不是模拟点击、不是 Selenium**。它是个**纯网络代理**，借用 Chrome 完整协议栈发请求。

```javascript
// extension 的核心代码就这么几行：
async function handleTask(url) {
  const response = await fetch(url, { credentials: "include" });
  // ↑ Chrome 自动带：HttpOnly cookie + 真 TLS 指纹 + HTTP/2 协议栈
  return await response.text();
}
```

### 2.2 为什么不能直接用 Python requests？

链家系级别的反爬识别**至少 5 层**，Python 都伪不了：

| 层级 | Python requests | Chrome 自己发 |
|------|-----------------|--------------|
| **HttpOnly cookie** | ❌ 拿不到（JS/Python 看不见） | ✅ 自动注入 |
| **TLS 指纹（JA3/JA4）** | ❌ openssl ≠ Chrome | ✅ 真 Chrome 指纹 |
| **HTTP/2 协议参数** | ❌ 默认 HTTP/1.1 | ✅ HTTP/2 + 特有 SETTINGS |
| **动态签名（页面 JS 算）** | ❌ 要逆向 JS | ✅ 页面 JS 自己算 |
| **登录维护** | ❌ 短信/扫码每次重来 | ✅ 用户扫码一次，cookie 长期有效 |

### 2.3 业界三种方案对比

| 方案 | 做什么 | 通过率 | 适合 |
|------|--------|--------|------|
| Python requests | 自己造 HTTP | ❌ 几乎为零 | 反爬弱站点 |
| **Housing Bridge（我们）** | **Chrome 后台 fetch** | ✅ 高 | **取数据型任务** |
| Selenium / Playwright | 模拟用户全套 UI | ✅ 高 | 需 SPA 交互 |
| Bright Data 商业代理 | 商业 IP 池 + 抗反爬 | ✅ 高 | 大规模商业用 |

Housing Bridge 是 "Python 直连" 和 "Selenium 模拟" 之间的**第三条路**：比 requests 可靠，比 Selenium 轻量，对"取数据"场景最优。

### 2.4 一个完整请求的链路

```
skill (Python)            Chrome 内（已登录目标站点）         站点服务器
     │                          │                                  │
     │ ① POST /fetch {url}                                          │
     │ ────→ bridge_server 排队 │                                  │
     │                          ↑                                  │
     │           ② extension long-poll 拿到任务                     │
     │                          │                                  │
     │                          │ ③ Chrome 内 fetch(url):           │
     │                          │   - 自动注入 cookie               │
     │                          │   - 真 TLS 指纹                  │
     │                          │ ──────────────────────────────→ │
     │                          │ ← 60KB HTML（已登录正常响应）── │
     │                          │                                  │
     │           ④ extension POST /result 上报 HTML                 │
     │ ← HTML                                                       │
     │                                                              │
     │ ⑤ skill 用对应站点 adapter 解析 HTML                          │
```

服务器在协议层无法区分"用户手动点"和"extension 自动 fetch"，因为 TLS / cookie / 协议栈完全一样。

---

## 3. 架构（多站点适配器模式）

```
                  ┌─ user's Chrome ─────────────────┐
                  │ Housing Bridge 扩展              │
                  │  - manifest 含多个 host_perms    │
                  │  - SW 监听 bridge → fetch url    │
                  │  已登录 lianjia / ke / anjuke...  │
                  └────────────┬─────────────────────┘
                               │ HTTP long-poll
                               ↓
                  ┌─ housing_bridge_server.py ──────┐
                  │ port 9334                       │
                  │  /fetch /poll /result /health    │
                  └────────────┬─────────────────────┘
                               │ HTTP
                               ↓
                  ┌─ sources/housing_bridge.py ─────┐
                  │ 统一 fetch 客户端                │
                  └────────────┬─────────────────────┘
                               │ 调
                               ↓
            ┌────── sources/site_adapters/ ────────┐
            │  - lianjia.py / ke.py（Phase 1）     │
            │  - ziroom.py（Phase 2 预留）         │
            │  - anjuke.py / _58.py / fang.py      │
            │     （Phase 3 预留）                 │
            │  - 每个 adapter 实现 SiteAdapter 协议 │
            │     parse_community / parse_listing  │
            └────────────┬─────────────────────────┘
                         │ 输出统一 schema
                         ↓
                  CommunityInfo / Listing / PriceInfo
                         │
                         ↓
                  rental.py / community_search.py 等
                  (业务逻辑层，不感知数据来源)
```

**关键差异（vs xhs-skills）**：
- xhs 用 WebSocket + cli.py（多种语义 API）
- housing-bridge 用 HTTP polling + 直接 sources 调用（单一原子操作 fetch URL）

---

## 4. 设计决策（已定，待你 review）

| # | 决策 | 选择 | 理由 |
|---|------|------|------|
| D1 | bridge 进程 | **独立 process**，监听 port **9334** | 故障域隔离；用户独立 Ctrl+C；不污染 xhs-skills |
| D2 | 通信协议 | **HTTP polling** | 单向请求-响应足够；调试用 curl 即可；service worker 不会因 30s 闲置断 |
| **D3** | **站点抓取策略** | **多站点适配器模式**。Phase 1 启用 lianjia + ke（同模板，共享 parser）；架构预留 anjuke/58/fang/ziroom 等 | 一次做完成本爆炸（每个站点 HTML 不同，要单独逆向）；分 Phase 推进 ROI 最高 |
| **D4** | **extension 注入方式** | **仅 Service Worker（background.js）**，不写 content.js | SW 直接 `fetch(url, {credentials:"include"})` 即可让 Chrome 自动注入 cookie；不操作 DOM 故省 content.js |
| D5 | bridge_server 跟 xhs 的关系 | **完全独立** | 用户要装两个 extension、启两个 server，但权责清晰 |
| D6 | extension 放在 house-hunter 项目内 | **`extension/` 子目录** | 跟着 skill 走，git pull 即更新 |
| D7 | 速率限制 | **每次 fetch 至少 3s 间隔 + 单会话累计 ≤ 80 次** | 保护用户账号 |
| D8 | 缓存 TTL | 详情页 7 天、挂牌列表 24h、搜索 6h | 元数据慢、挂牌天级、搜索小时级 |
| **D9** | **数据统一 schema** | 定义 `CommunityInfo` / `Listing` / `PriceInfo` 三个 dataclass，每个 adapter 输出统一格式 | 上层业务逻辑不感知数据源；后续加站点只需写新 adapter |
| **D10** | **多站点优先顺序**（v5 修订 2026-05-11）| **ke → lianjia → anjuke → ziroom → 58 → fang** | 用户决策：**贝壳是首选**，链家作 ke 另一入口；anjuke 独立数据源（区准）；ziroom 长租公寓；58/fang 个人/老牌兜底。代码：`site_adapters/__init__.py::all_adapters()` |

---

## 5. 文件清单 + 接口契约

### 5.1 新增文件

```
house-hunter/
├── extension/                              ← Chrome Extension (Housing Bridge)
│   ├── manifest.json                       ← ~35 行：MV3 + 多域 host_permissions
│   ├── background.js                       ← ~150 行：long-poll + fetch + 心跳
│   ├── popup.html                          ← ~50 行（可选）：显示各域登录状态
│   └── README.md                            装载步骤截图
├── scripts/
│   ├── housing_bridge_server.py            ~120 行：HTTP server + task queue
│   └── sources/
│       ├── housing_bridge.py               ~80 行：通用 bridge 客户端
│       └── site_adapters/
│           ├── __init__.py                 ~30 行：SiteAdapter 协议定义 + 注册中心
│           ├── lianjia.py                  ~120 行 (Phase 1)：链家 HTML parser
│           ├── ke.py                       ~50 行 (Phase 1)：贝壳（继承 lianjia，URL 替换）
│           ├── ziroom.py                   ~120 行 (Phase 2 预留，可空文件占位)
│           ├── anjuke.py                   (Phase 3 预留)
│           ├── _58.py                      (Phase 3 预留)
│           └── fang.py                     (Phase 3 预留)
└── docs/
    └── plan-lianjia-bridge.md              ← 本文件
```

**注意**：不写 `content.js`（详见 D4）。Phase 2/3 的 adapter 现在不写（D3）。

### 5.2 manifest.json 示例

```json
{
  "manifest_version": 3,
  "name": "Housing Bridge (house-hunter)",
  "version": "1.0.0",
  "description": "house-hunter 配套扩展：让 skill 通过你已登录的 Chrome 抓多家房产平台",
  "permissions": ["alarms"],
  "host_permissions": [
    "*://*.lianjia.com/*",
    "*://*.ke.com/*",
    "*://*.ziroom.com/*",
    "*://*.anjuke.com/*",
    "*://*.58.com/*",
    "*://*.fang.com/*",
    "http://localhost:9334/*"
  ],
  "background": { "service_worker": "background.js" },
  "action": {
    "default_popup": "popup.html",
    "default_title": "Housing Bridge"
  }
}
```

**注意**：manifest 一次性把所有未来站点都申明了，**Chrome 装的时候用户会看到完整权限列表**（这是 Chrome 的安全机制 — 你装这个扩展就授权了所有这些域名访问，扩展后续不能偷偷加新域）。

### 5.3 统一数据 schema（D9）

```python
# sources/site_adapters/__init__.py
from dataclasses import dataclass
from typing import Protocol

@dataclass
class CommunityInfo:
    """归一化的小区信息（任何站点都映射到这个 schema）"""
    name: str
    city: str
    district: str | None
    address: str | None
    lat: float | None
    lng: float | None
    built_year: int | None         # 建成年份
    building_count: int | None      # 楼栋数
    unit_count: int | None          # 户数
    property_company: str | None    # 物业公司
    source: str                     # "lianjia" / "ke" / "anjuke" ...
    source_id: str                  # 该平台的小区 id
    url: str                        # 原始 URL（可点开验证）

@dataclass
class Listing:
    """单条房源挂牌"""
    listing_id: str
    community_name: str
    rooms: int                      # 几室
    halls: int                      # 几厅
    area_sqm: float
    floor: str | None               # "中楼层/共 18 层"
    facing: str | None              # 朝向
    decoration: str | None          # 装修类型
    rent_yuan_per_month: int | None # 月租金
    sale_price_wan: int | None      # 出售总价（万）
    posted_date: str | None         # 挂牌日期 ISO
    source: str
    url: str

@dataclass
class PriceInfo:
    """小区价格汇总（按户型分布）"""
    community_id: str
    source: str
    one_bedroom: dict   # {"avg":..., "min":..., "max":..., "count":...}
    two_bedroom: dict
    three_bedroom: dict
    shared_room: dict
    total_listings: int

class SiteAdapter(Protocol):
    """每个 adapter 必须实现的接口"""
    SITE_NAME: str

    def search_community_url(self, city: str, district: str | None) -> str: ...
    def community_detail_url(self, community_id: str, city: str) -> str: ...
    def listings_url(self, community_id: str, city: str) -> str: ...

    def parse_search(self, html: str) -> list[CommunityInfo]: ...
    def parse_community_detail(self, html: str) -> CommunityInfo: ...
    def parse_listings(self, html: str) -> list[Listing]: ...
```

加新站点（Phase 2/3）= **写一个新 adapter 实现这个 Protocol**，业务层零修改。

### 5.4 接口契约（bridge_server）

不变（同 v2）：
- `GET /health` → 状态总览
- `POST /fetch {url}` → 通过 extension 抓 HTML
- `GET /poll` → extension 长轮询
- `POST /result` → extension 上报
- `POST /heartbeat` → extension 心跳 + 登录态

### 5.5 改造现有文件

```
scripts/sources/rental.py
  └── fetch_html() 加 bridge fallback：先直爬 → bridge → 返 None

scripts/status.py
  └── 加检查：
        housing_extension_installed
        housing_bridge_running
        housing_logged_in_sites   ← 返回已登录的站点列表 ["lianjia","ke"]
        legacy_directly_fetch_works

SKILL.md
  └── 加 Step 0.D「Housing Bridge 安装与启动」（仿照 Step 0.B）

README.md / README.zh-CN.md  加一节「Housing Bridge 模块」（双语同步）
```

---

## 6. 实施阶段（Phase 1：6 个里程碑）

| # | 里程碑 | 验证 | Claude 工时 | 用户介入 |
|---|--------|------|------------|---------|
| M1 | manifest + background.js + housing_bridge_server 骨架 | bridge_server 启动看到 "listening on :9334"；chrome 加载 extension 后状态汇报 | ~60 min | M1 完成后才进 M2 |
| M2 | **★ 你装 extension + 登录 lianjia 或 ke ★** | extension popup 显示 connected + logged in | ~5 min | **3 步** |
| M3 | /fetch 路由 + SW fetch 逻辑 | curl `POST /fetch -d '{"url":"sz.lianjia.com/xiaoqu/2810/"}'` 拿到真 HTML | ~30 min | 无 |
| M4 | site_adapters/__init__.py + lianjia.py + ke.py + housing_bridge.py | 单测 `LianjiaAdapter.parse_community_detail()` 返回 CommunityInfo（含 built_year） | ~50 min | 无 |
| M5 | rental.py fallback + status.py + SKILL.md Step 0.D | `status.py --json` 含 housing_* 字段 | ~30 min | 无 |
| M6 | e2e 重跑龙岗用例 | Top 5 都有建成年份；rental 分非 50 | ~30-60 min | 万一被风控配合 |

**总：约 3.5-4.5 小时单 session 能跑通 M1-M6**。

---

## 7. 你必做项（4 件事 + 为什么 Claude 做不了）

| # | 你要做 | 触发时机 | 耗时 | 为什么 Claude 做不了 |
|---|--------|---------|------|---------------------|
| **U1** | Chrome 加载已解压的扩展 | M2 一次，永久 | ~2 min | `chrome://extensions` 是 Chrome 内置 UI，Chrome 安全策略不允许任何外部程序自动批准加载未签名扩展 |
| **U2** | Chrome 里登录 lianjia.com 或 ke.com（任一） | M2 一次 | ~1 min | 链家登录需手机+短信/扫码，是**你身份认证**，Claude 不可代 |
| **U3** | 前台启动 `python3 scripts/housing_bridge_server.py` | 每次开新 session 首用 | ~10 秒 | SKILL.md 强约束：LLM 严禁后台启动 bridge（参考 Step 0.B） |
| **U4** | 风控警告时配合二次验证 | < 5% 概率 | ~30 秒 | 风控需你身份认证 |

**U1+U2+U3 一次性总耗时：~3 分钟**。

### Phase 2/3 加新站点时的额外用户介入
- 用 ziroom（自如）数据 → 你要去 ziroom.com 登一次（一次性）
- 用 anjuke / 58 数据 → 同上
- 不强求 — 没登录的站点 adapter 自动跳过

---

## 8. 风险点 + 应对

| 风险 | 影响 | 应对 |
|------|------|------|
| 链家/贝壳页面结构变化 | parser 正则失效 | 解析失败 → 返原始 HTML 让 LLM 兜底；adapter 单元测试用真实 fixture 早发现 |
| 某个域反爬突然加强 | 该域不可用 | D10 多站点 fallback 自动接管 |
| 用户**所有支持的域都没登录** | bridge 拿到登录页 | extension 检测"登录" title 上报；skill 端熔断；告知用户登录任一域 |
| 风控警告/封号 | 账号禁用 | D7 限速 + D8 缓存 + 熔断 |
| Service Worker 被 Chrome 杀（MV3 通病） | extension 断 | `chrome.alarms` 25 秒唤醒 + long-poll 未完成 fetch 保活 |
| Bridge 端口冲突（9334 被占） | 启动失败 | `--port` 覆盖 |
| 并发：xhs + housing 同时跑 | 互相干扰 | 不会 — 各管各的域，各占自己端口 |
| 多站点 cookie 互相污染 | 用 lianjia cookie 访问 ke 出错？ | Chrome 按域隔离 cookie jar，自动正确路由 |
| Phase 2/3 站点 HTML 升级 | 单个 adapter 失效 | adapter 隔离，单个失败不影响其他；fallback 顺序自动转下一个 |

---

## 9. e2e 验证用例（Phase 1）

### 用例 1：龙岗用例重跑
```bash
python3 scripts/house_hunter.py \
  --requirement-file /tmp/hh_req.json \
  --save-dir "$HOME/Documents/House-Hunter" --json
```
**验收点**：来源 `lianjia_full` 或 `ke_full`；Top 5 都有建成年份；rental 分非 50。

### 用例 2：bridge 关闭 → 优雅降级到百度 POI
**验收点**：引擎不崩溃，报告标注"链家/贝壳数据不可用"。

### 用例 3：bridge 在跑但 chrome 未登录
**验收点**：`status.py` 检测 `housing_logged_in_sites=[]`，给出明确提示，熔断不发请求。

### 用例 4：lianjia 域挂掉 → 自动切贝壳
**验收点**：日志记录 `source_used=ke`，e2e 仍出完整报告。

---

## 10. 已排除的备选路径（决策记录）

| 路径 | 排除原因 |
|------|---------|
| 贝壳开放平台 OAuth2 API | 配额需谈商务合作（实测 `code:-2001 没有剩余配额`） |
| Apify / GitHub 现成 lianjia 爬虫 | 国外 IP 劣势 + "仅供学习"声明 |
| Bright Data Web Unlocker | $500/月，不能让普通用户共用你额度 |
| 阿里云 API 市场 / 聚合数据 | 房产数据稀缺 |
| Python requests 模拟 Chrome | TLS/HTTP2/HttpOnly/动态签名 4 层伪不了 |
| Selenium / Playwright | 资源开销大 + 浏览器指纹易识别 + 不能复用用户登录态 |

**结论**：「免费 + 普通用户 + 合规」三约束下，**浏览器扩展接管是唯一可行路径**。

---

## 11. 多站点扩展路径（Phase 2/3 预案）

### 站点矩阵（按优先级）

| 站点 | 公司 | 主营 | 字段覆盖 | 反爬强度 | adapter 工作量 | Phase |
|------|------|------|---------|---------|----------------|-------|
| lianjia.com | KE | 自营中介，**深圳挂牌量最大** | 建成年份/物业/户数/挂牌价 | 高 | — | **1（必）** |
| ke.com | KE | 平台聚合 lianjia + 其他中介 | 同上（共享数据库） | 高 | — | **1（必）** |
| ziroom.com（自如） | KE | 长租公寓品牌 | **合租主卧均价**（核心补充）/ 公寓品牌 | 中 | ~120 行 | 2（可选） |
| anjuke.com（安居客） | 58 | 综合二手房/租房 | 中介房源 | 高 | ~150 行 | 3（可选） |
| 58.com 房产 | 58 | 综合分类信息 | 个人房东 | 高 | ~150 行 | 3（可选） |
| fang.com（房天下） | 房天下 | 老牌房产门户 | 新房/二手房 | 中 | ~120 行 | 3（可选） |

### Phase 2 决策点（未来 review）
- 用户反馈"合租信息不够"→ 加 ziroom
- 用户反馈"小城市没数据"→ 加 anjuke（覆盖广）

### Phase 3 决策点
- 用户反馈"想要个人房东直租"→ 加 58
- 用户反馈"新房信息缺失"→ 加 fang.com（但 fang.com 偏买房视角，跟本 skill 定位略冲突）

### 每加一个新站点的工作量（估算）
1. 注册一个 Chrome host_permission（manifest 加一行）：1 min
2. 写 adapter parser（HTML 逆向 + 单测）：1-3 小时
3. 加 Step 0.D 引导用户登录该站点：5 min
4. 加 fallback 顺序到 D10：1 min

**架构预留好，Phase 2 加 ziroom ≈ 2-3 小时 single session**。

---

## 12. 后续可选优化

- chrome extension UI 美化（带各域登录状态图标）
- 多账号支持（同一域多个账号轮换 — 反爬安全 + 配额上）
- 自动检测 HTML 结构变化报警
- Chrome Web Store 上架（省去开发者模式，但需 $5 + 审核）
- 加 fang.com 商业地产数据（如果未来扩到买房视角）

---

## 13. 关于这份 plan

- v1 → v2：D2 改 HTTP polling、加贝壳支持、加贝壳 OAuth 实测排除
- v2 → v3：升级到多站点架构 + Phase 划分 + 统一数据 schema (D9/D10)
- 核心价值：① 8+2 个设计决策落到纸面 ② §2 把原理写清 ③ §11 多站点扩展路径

---

## ⏭ 等你 review

请逐项 review：
1. D1-D10 设计决策有没有想推翻的？**特别是 D3（分 Phase）和 D10（fallback 顺序）**
2. Phase 1 仅做 lianjia + ke 你接受吗？还是想一次做更多？
3. §11 站点扩展路径里，**Phase 2 的 ziroom 你觉得现在就要做吗**？（如果要，M4 增加 0.5h）
4. U1-U4 你介入点你能接受吗？
5. 风险点有没有遗漏？

确认 → 立即开始 M1。
