# 🏗️ house-hunter 架构详解

> 多平台 Skill（Claude Code + OpenClaw），SKILL + Engine 混合架构，多源数据融合。

## 1. 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│ 用户在 Claude Code / OpenClaw 输入                               │
│   /house-hunter "坪山 70平 2房1厅 山姆 IMAX 预算4000"             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ SKILL.md (LLM 主导)    │
              │ ├─ Step 0 环境检查      │
              │ ├─ Step 1 解析需求      │
              │ │   (lifestyle 识别)    │
              │ │   (POI 类别识别)      │
              │ │   (回显确认)          │
              │ └─ Step 2 调用 engine   │
              └────────────┬───────────┘
                           │ requirement.json
                           ▼
              ┌────────────────────────┐
              │ house_hunter.py (引擎) │
              │ ├─ 1. 候选小区生成       │
              │ ├─ 2. 并行多源采集       │
              │ ├─ 3. 综合评分          │
              │ ├─ 4. 排序 + Top N      │
              │ └─ 5. Jinja2 渲染       │
              └────────────┬───────────┘
                           │
        ┌──────────────────┼──────────────────┬──────────────┐
        ▼                  ▼                  ▼              ▼
   ┌─────────┐         ┌─────────┐        ┌─────────┐  ┌─────────┐
   │配套层    │         │租金层    │        │口碑层    │  │安全层    │
   │baidu_map│         │rental   │        │xhs       │  │news_     │
   │amap     │         │community│        │(复用)    │  │search    │
   │         │         │_search  │        │          │  │xhs       │
   └─────────┘         └─────────┘        └─────────┘  └─────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ Markdown 报告           │
              │ ~/Documents/           │
              │ House-Hunter/          │
              │ {topic}-{date}.md      │
              └────────────┬───────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │ SKILL.md Step 3-5      │
              │ ├─ LLM 二次合成（按引用规范）│
              │ ├─ 保存最终报告         │
              │ └─ 邀请后续提问         │
              └────────────────────────┘
```

## 2. 三层架构

| 层 | 职责 | 关键文件 |
|----|------|---------|
| **接口层** | 对话编排、LLM 解析、用户交互 | `SKILL.md` |
| **业务层** | 流程编排、评分、报告合成 | `scripts/house_hunter.py` `scripts/analyzers/*.py` |
| **数据层** | 各 MCP/API 调用封装、缓存、降级 | `scripts/sources/*.py` |

## 3. 模块职责

### 3.1 解析器（parsers/）

| 文件 | 职责 |
|------|------|
| `requirement_parser.py` | 校验 LLM 解析的 JSON schema，补充默认值，展开 POI 类别为搜索关键词 |
| `city_resolver.py` | 城市/区域名标准化（"坪山"→"深圳市/坪山区"），白名单外城市走地图 API 校验 |

### 3.2 数据源（sources/）

| 文件 | 数据源 | 主要 API |
|------|-------|---------|
| `baidu_map.py` | 百度地图（fallback#1，主源，5000/天） | geocode / reverse_geocode / search_nearby / search_in_region / directions |
| `amap.py` | 高德地图（fallback#2，100/天） | 同上接口 + 累积失败熔断 |
| `tianditu.py` | 天地图（fallback#3，**10000/天**，国家测绘局） | search_nearby / search_in_region / geocode + 累积失败熔断 |
| `xhs.py` | 小红书（复用 xiaohongshu-skills） | community_reviews / district_vibe / safety_search / single_woman_reviews |
| `rental.py` | 链家 / 贝壳 / 自如 | top_communities / community_rental_summary / community_basic_info |
| `news_search.py` | Bing 中国 / 百度搜索 | bing_search / safety_incidents |
| `community_search.py` | 候选生成统一入口 | find_candidates（链家优先 + 百度地图 POI 兜底） |

### 3.3 分析器（analyzers/）

| 文件 | 输入 | 输出 |
|------|------|------|
| `poi_validator.py` | 小区 + POI 规格 | 各类别 POI 列表 + 是否满足 must-have |
| `lifestyle_matcher.py` | lifestyle 画像 + POI 类别分数 | 加权后的总分 + 按顶层类别分解 |
| `rental_analyzer.py` | 小区 ID + 城市 | 一房/两房/三房/合租均价 + 租金合理性分 |
| `commute_simulator.py` | 起点坐标 + 目的地 | 三种交通方式的耗时 |
| `safety_checker.py` | 小区名 + 城市 | 风险事件列表 + 严重等级分布 + 安全分 |
| `sentiment_aggregator.py` | 小区名 + 城市 | 按维度（物业/噪音/邻居/...）聚合的口碑分 |
| `community_scorer.py` | 上述各维度结果 | 综合分 0..100 + 各分项 |

### 3.4 报告合成（reports/）

| 文件 | 职责 |
|------|------|
| `templates/search.md.j2` | 用例 A 找房模板：候选表 + Top 3 推荐 + 妥协方案 |
| `templates/deep_dive.md.j2` | 用例 B 调研模板：横向对比表 + 每小区 4 维度 + lifestyle 推荐 |
| `render.py` | Jinja2 渲染引擎（StrictUndefined 严格模式） |

## 4. 评分模型

### 4.1 主权重（年轻租客视角，可在 `config/scoring.yaml` 调整）

| 维度 | 权重 | 备注 |
|------|------|------|
| 配套契合度（POI × lifestyle） | 40% | 主要差异化点 |
| 租金合理性 | 20% | 与预算 + 同区均价对比 |
| 居住口碑（小红书聚合） | 20% | 物业/噪音/邻居/独居 |
| 安全 | 15% | 凶案/跳楼/火灾/纠纷 |
| 通勤 | 5% | 仅当用户指定目的地 |

> 用户未指定通勤目的地 → 通勤的 5% 自动并入配套，权重 → 45%。
> 女生独居画像 → 安全权重 +5（最多到 +8）。

### 4.2 子权重 — Lifestyle 加权

每个 lifestyle 画像在 `config/lifestyle_profiles.yaml` 定义对 7 大类别的权重乘数：

```yaml
homebody:
  category_weights:
    shopping: 1.5         # 便利店/超市更重要
    dining: 1.5           # 外卖密度
    entertainment: 0.5    # 不爱出门
    nature: 0.6
    transport: 0.7
    medical: 1.0
    life_service: 1.2
```

多个画像合并 → 每类取最大值（不无限叠加）。

### 4.3 各分项算法

- **POI 评分**（每个子类别 0..10）：50% 数量分（满足 min_count → 5 分）+ 50% 距离分（按 default_radius 归一化）
- **租金评分**（0..100）：在预算内 100；超 10% 内 80；超 20% 内 50；超 20% 以上 20
- **口碑评分**（0..100）：(positive×1.0 - negative×1.5) / total，映射到 0..100；笔记数 < 5 时置 50（中性）
- **安全评分**（0..100）：从 100 起扣，high -30，medium -12，low -4；零事件取 floor 80（"未查到 ≠ 没发生"）
- **通勤评分**（0..100）：阈值 30/45/60/90 分钟分别对应 100/80/60/30

## 5. 数据流细节

### 5.1 候选生成（critical path）

```python
# scripts/sources/community_search.py
def find_candidates(city, district, area, limit) -> tuple[list, source_label]:
    if rental.is_lianjia_supported(city):
        candidates = rental.top_communities(...)     # 路径 A: 精细
        if candidates: return candidates, "lianjia_full"
    # 路径 B: 兜底（任意城市可用）
    return baidu_map.search_in_region("小区", region), "baidu_map_poi"
```

链家增强白名单（`CITY_PINYIN`）覆盖 80+ 城市，未命中走百度地图 POI。

### 5.2 并行采集

```python
# scripts/house_hunter.py
enriched = parallel_map(_enrich_one, candidates, max_workers=3)
# _enrich_one 内部对单个小区做：
#   - POI 校验（POI 类别再并行 max_workers=6）
#   - 租金分析（仅链家来源）
#   - 小红书口碑（多关键词并行）
#   - 安全事件（多关键词并行）
#   - 通勤模拟（如指定目的地）
```

整体并发 ≈ 3 × 6 = 18 路并行，受限于：
- 百度地图 QPS
- 小红书 MCP 单进程
- WebFetch 速率（≥2.5s）

### 5.3 缓存策略

| 命名空间 | TTL | 说明 |
|---------|-----|------|
| `baidu_geocode` / `amap_geocode` | 7 天 | 地理编码不常变 |
| `baidu_search_*` / `amap_search_*` | 24 小时 | POI 列表 |
| `rental_html` / `rental_top` | 24 小时 | 链家页面 |
| `xhs_search` | 6 小时 | 笔记可能新增 |
| `bing_search` / `baidu_news_search` | 6 小时 | 安全事件需要相对新鲜 |

缓存命中时不消耗 API 配额。

### 5.4 降级路径

```
百度地图调用失败（含累积 3 次熔断）
  ├→ 尝试高德地图（同接口，也有累积熔断）
  ├→ 尝试天地图（fallback#3，国家测绘局，1 万次/天）
  └→ 全部失败 → 跳过 POI 校验，标注「地图不可用」

链家页面 404 / 反爬
  ├→ 尝试贝壳（同 URL 模式不同子域）
  ├→ 尝试自如（合租优先）
  └→ 全部失败 → 走百度地图 POI 兜底

xiaohongshu-skills 未运行 / 未登录
  └→ 跳过口碑维度，安全只走 WebSearch（精度下降）

WebSearch 失败
  └→ 跳过新闻搜索，安全只走 xhs（如果可用）
```

## 6. SKILL.md 编排

### Step 0: 环境检查
- 调用 `scripts/status.py --json`，根据 `fixes` 数组指导用户修复
- 6 类修复动作：`install_python_deps` / `configure_baidu_key` / `configure_amap_key` / `install_xhs_research` / `start_xhs_mcp` / `login_xhs`

### Step 1: LLM 解析需求
- 识别意图（search / research）
- 识别 lifestyle 画像（最多 2 个）
- 识别 POI 类别（含品牌 must_have_brand）
- 城市/区域标准化
- 回显确认

### Step 2: 调用引擎
```bash
python3 ${SKILL_ROOT}/scripts/house_hunter.py \
  --requirement-file /tmp/req.json \
  --save-dir ~/Documents/House-Hunter
```

### Step 3-5: LLM 二次合成 + 保存 + 邀请后续

引擎已经渲染了一份 Markdown，但 LLM 可以基于原始数据做更人话的二次合成（按 xiaohongshu-skills 的引用规范）。

## 7. 多平台兼容（Claude Code / OpenClaw）

`SKILL.md` 通过环境变量发现 skill 安装路径：

```bash
for dir in \
  "${CLAUDE_PLUGIN_ROOT:-}" \
  "${OPENCLAW_SKILL_ROOT:-}" \
  ...; do
  [ -f "$dir/SKILL.md" ] && SKILL_ROOT="$dir" && break
done
```

frontmatter 同时声明两种平台元数据：

```yaml
metadata:
  openclaw:
    emoji: "🏠"
    requires:
      bins: [python3, git]
  # claude_code: 用 user-invocable: true 顶层字段
```

复用 xiaohongshu-skills 的设计模式，零改动可在两个平台运行。

## 8. 与 xiaohongshu-skills 的关系

house-hunter **直接复用 xiaohongshu-skills 的 xiaohongshu-mcp 后端**（不重新部署）：

```python
# scripts/_common.py
XHS_MCP_BASE = "http://localhost:18060"  # xiaohongshu-skills 启动的服务

# scripts/sources/xhs.py
def is_available() -> bool:
    return check_xhs_running() and check_xhs_logged_in()
```

如果 xiaohongshu-skills 没运行，house-hunter 自动跳过口碑维度，安全部分只走 WebSearch。
