# 📡 数据源说明

各数据源的使用方式、限制、降级策略。

## 0. 三层地图 fallback 总览（v2，2026-05）

```
查询请求
   ↓
1. 百度地图（fallback#1，主源） — 5000 次/天免费
   - 失败 N=3 次累积 → 整会话熔断 → 后续直接 None
   ↓ 返回 None
2. 高德地图（fallback#2，备用） — 100 次/天免费
   - 同样累积失败 3 次熔断
   ↓ 返回 None
3. 天地图（fallback#3，兜底） — **10000 次/天免费**，国家测绘局官方
   - 同样累积失败 3 次熔断
   ↓ 返回 None
4. 全部失败 → 调用方按需降级
```

**总免费配额：~15,100 次/天**，远超日常使用。

### POI keyword 设计（v2 改进，配额省 5-10x）

config/poi_categories.yaml 每个子类拆分两个字段：

```yaml
big_supermarket:
  primary_keywords: [超市]                      # ← 调 API 用，1-3 个泛用词
  brand_keywords: [山姆, 沃尔玛, 永辉, ...]    # ← 不调 API，仅用于显示品牌
  expected_tags: [超市, 仓储会员店, 大卖场]    # ← POI tag/type 强校验
```

效果：单类别 API 调用从 10 次（每个品牌名一次）降到 1-3 次（每个泛用词一次），仍能精准过滤。

---

## 1. 百度地图（主）

- **官网**：https://lbsyun.baidu.com/
- **申请 Key**：https://lbsyun.baidu.com/apiconsole/key（应用类型选「服务端」）
- **环境变量**：`export BAIDU_MAPS_API_KEY=<your_ak>`
- **配额**：默认每日 5000 次免费（个人开发者认证后可申请更多）
- **限制**：单次请求 page_size 最大 20

### 用到的 API

| API | 用途 | 缓存 |
|-----|-----|------|
| `/geocoding/v3/` | 地址 → 坐标 | 7 天 |
| `/reverse_geocoding/v3/` | 坐标 → 地址 | 7 天 |
| `/place/v2/search?region=...` | 城市内 POI 关键词搜索 | 24h |
| `/place/v2/search?location=...&radius=...` | 周边搜索 | 24h |
| `/directionlite/v1/{mode}` | 路线规划（驾车/步行/公交/骑行） | 1h |

### 失败时的降级
失败 → 自动尝试高德地图（接口对齐）

## 2. 高德地图（备用，fallback#2）

- **官网**：https://lbs.amap.com/
- **申请 Key**：https://lbs.amap.com/api/webservice/create-project-and-key（类型选「Web服务」）
- **环境变量**：`export AMAP_MAPS_API_KEY=<your_key>`
- **配额**：默认每日 100 次（个人）/ 30000 次（认证企业）

### 与百度的差异
- POI 数据在不同区域各有优势（高德在三四线城市略优）
- 坐标系：高德是 GCJ-02，百度是 BD-09，本项目内部统一不做转换（因为同源使用，距离计算用 haversine 影响极小）

## 2.5 天地图（兜底，fallback#3）

- **官网**：http://lbs.tianditu.gov.cn/
- **申请 Key**：http://lbs.tianditu.gov.cn/authorization/authorization.html（应用类型选「服务端」）
- **环境变量**：`export TIANDITU_API_KEY=<your_tk>`
- **配额**：**1 万次/天免费**（远超百度 5000 / 高德 100，最慷慨的一家）
- **来源**：国家测绘地理信息局（gov.cn 域名，权威）

### 用到的 API（全部 GET）

| API | 用途 | 缓存 |
|-----|------|------|
| `/v2/search?queryType=3` | 周边搜索（pointLonlat + queryRadius） | 24h |
| `/v2/search?queryType=7` | 行政区划搜索（specify=区域名） | 24h |
| `/geocoder` | 地理编码（地址 → 坐标） | 7 天 |

请求格式：`postStr` URL-encoded JSON + `type=query` + `tk=KEY`

注意：**lonlat 顺序是「经度,纬度」**（与高德一致，与百度相反）。

### 状态码

- `infocode: 1000` = 服务正常
- 其他 = 错误 / 配额超限 → 触发熔断计数

### 失败时的降级
全部失败 → 调用方按需降级

---

## 3. 小红书（复用 xiaohongshu-skills）

- **官网**：https://www.xiaohongshu.com/
- **复用项目**：[autoclaw-cc/xiaohongshu-skills](https://github.com/autoclaw-cc/xiaohongshu-skills)
- **后端**：xiaohongshu-mcp（Go 二进制，监听 `localhost:18060`）
- **登录**：cookie 持久化（QR code 扫码一次，长期有效）

### 用到的 API（通过 xiaohongshu-skills）

| API | 用途 | 缓存 |
|-----|-----|------|
| `POST /api/v1/feeds/search` | 关键词搜索笔记 | 6h |
| `POST /api/v1/feeds/detail` | 单笔记完整正文 + 评论 | 6h |

### house-hunter 的高层封装（`sources/xhs.py`）
- `community_reviews(name, city)` — 小区住户口碑（多关键词并行）
- `district_vibe(district, city)` — 区域氛围
- `safety_search(community)` — 风险事件
- `single_woman_reviews(community)` — 女生独居视角
- `pet_friendly_check(community)` — 养宠友好度

### 失败时的降级
xiaohongshu-skills 不可用 → 报告中口碑维度标注「数据不可用」，安全维度仅靠 WebSearch

## 4. 链家 / 贝壳 / 自如（租金）

- **抓取方式**：WebFetch（不直接爬虫）+ 节流（≥2.5s 间隔）+ 缓存（24h）
- **不需要 Key**

### 增强白名单
`scripts/sources/rental.py` 中的 `CITY_PINYIN` 字典覆盖 80+ 城市的链家子域名映射。
不在白名单的城市 → 链家 URL 拿不到 → 走「百度地图 POI 搜小区」兜底。

### 用到的页面

| URL 模板 | 用途 |
|---------|------|
| `https://{city}.lianjia.com/zufang/{district}/` | 区级租房列表（解析 → 候选小区） |
| `https://{city}.lianjia.com/zufang/c{community_id}/` | 单小区租房列表（一房/两房/三房/合租均价） |
| `https://{city}.lianjia.com/xiaoqu/{community_id}/` | 小区详情（建成年份、户数、物业） |

### 解析策略
- 正则匹配（不依赖第三方 HTML 解析库，标准库即可）
- 字段：户型、面积、月租、所属街道
- 失败时跳过 → 该小区租金标记为 `available: False`

## 5. 新闻搜索

- **使用引擎**：Bing 中国（cn.bing.com）+ 百度搜索（兜底）
- **不需要 Key**
- **节流**：≥1.5s 间隔
- **缓存**：6h（安全事件需要相对新鲜）

### 用到的搜索

| 函数 | 用途 |
|-----|-----|
| `bing_search(query)` | 通用搜索 |
| `safety_incidents(community, city)` | 多关键词并行（"凶案" / "跳楼" / "火灾" / "入室" / ...） |

### 限制
- 中国境内 Bing 偶尔不稳定（页面结构变动）
- 单条搜索结果质量参差，需要后续做严重等级和可信度判断

## 6. 候选小区生成统一入口

`scripts/sources/community_search.py` 的 `find_candidates(city, district, area, limit)` 是统一入口：

1. 城市在 `CITY_PINYIN` 白名单 → 链家精细数据（户型/挂牌量/挂牌价）
2. 链家失败或白名单外 → 百度地图 POI 关键词搜索（"小区" / "花园" / "公寓" / "城"）+ 类型过滤（"住宅"）
3. 全部失败 → 返回空列表，引擎报错并提示用户

返回的 `source_label` 字段告知调用方使用了哪条路径，影响后续是否做租金分析。

## 7. 数据降级总览

| 失败的源 | 降级动作 | 影响 |
|---------|---------|------|
| 百度地图 | → 高德地图 → 天地图 | 自动 fallback，无感 |
| 高德地图 | → 百度地图 → 天地图 | 自动 fallback，无感 |
| 天地图 | → 百度地图 → 高德地图 | 自动 fallback，无感 |
| 双地图都失败 | 报错退出 | 不可用（POI 是核心） |
| 链家页面 404 | → 百度地图 POI | 失去户型/挂牌量数据，仅有候选名 |
| xiaohongshu-skills 不可用 | 跳过口碑 + 安全部分仅靠 WebSearch | 评分中口碑分置为 50（中性），安全召回率下降 |
| WebSearch 失败 | 跳过新闻 | 安全部分只剩 xhs |
| 全部失败 | 走 fallback 到 fallback | 报告标注「多个数据源不可用，结果仅供参考」 |

## 8. 配额估算（单次完整查询）

假设候选小区 8 个，每个小区 6 个 POI 类别：

| 资源 | 估算用量 |
|------|---------|
| 百度地图（POI 搜索） | 8 × 6 = 48 次 |
| 百度地图（geocoding，候选补 lat/lng） | ≤ 8 次 |
| 链家 WebFetch | 1 + 8 = 9 次（区列表 + 单小区） |
| xiaohongshu-skills 搜索 | 8 × 6 ≈ 48 次（口碑 + 安全） |
| Bing 搜索 | 8 × 6 ≈ 48 次（安全多关键词） |

百度地图免费 5000 次/天 → 一次查询约消耗 1% 配额。

链家和 Bing 是网页抓取，主要受节流（2.5s + 1.5s）限制，单次完整查询耗时约 2-5 分钟。

## 9. 自定义/扩展

加新的数据源：
1. 在 `scripts/sources/` 下加新文件 `xxx.py`
2. 暴露统一接口（如 `community_summary(name, city)`）
3. 在 `scripts/analyzers/` 中调用
4. 在 `house_hunter.py` 的 `_enrich_one()` 中加调用
5. 在 `templates/*.j2` 中加渲染

加新的 POI 类别：
1. 编辑 `config/poi_categories.yaml`，加新的 subcategory
2. 在 `config/lifestyle_profiles.yaml` 的 `category_weights` 里设置该类的权重
3. 无需改代码（pipeline 自动识别）
