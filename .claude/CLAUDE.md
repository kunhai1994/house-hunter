# house-hunter — 项目级 Claude 指引

## 双语 README 同步

任何对 `README.md`（英文）或 `README.zh-CN.md`（中文）的修改，必须同步另一文件。

## 提交规范

- 中文 commit message 优先（与 xiaohongshu-skills 一致）
- 单一职责：一个 commit 一个目的

## 测试与验证（最重要）

- **跳过所有前置检查/检测**：不跑 status.py、不做健康检查、不验环境、不预防性测试
- **跳过 SKILL.md Step 0** 整段（开发者环境永远已配齐）
- **直接跑核心流程**：用户发来需求 → 解析 → 跑引擎 → 出报告，**这一条流水线**，不分支不绕路
- **跑完直接读报告交付**：不在中间 grep raw json、不抽中间数据做"诊断对比"
- **出问题再分析**：报告里发现明显坏数据时才分析 root cause + 修复 + 重跑；不预先怀疑/验证
- 改动如有 syntax/import 风险，可用一行 `python3 -c "import X"` 快验，**但绝不跑 status.py 或 e2e**

## 数据源调用约束

- **贝壳 (ke.com) 是房产数据的第一优先级**，链家仅作 fallback。所有 lianjia/ke 双 host 选择必须 ke 第一。详见 SKILL.md「数据源约束」节
- 所有外部 API 调用必须有缓存（默认 24h，安全类 6h）
- 网页抓取（贝壳/链家）必须 ≥2s 间隔
- 多源 fallback 顺序：地图 POI 百度→高德→天地图；房产数据 ke→lianjia→anjuke→ziroom→58→fang

## 报告输出原则

- 每个事实必须附来源链接（参考 xiaohongshu-skills 的引用规范）
- 安全事件谨慎措辞："未查到"≠"没发生"
- 不夸大单条事件代表性
- **建成年份必填**：ke/lianjia/anjuke 三层 resolution 都没拿到时，**必须**用 WebSearch 兜底（详见 SKILL.md Step 2.5）。禁止直接交付缺年份的报告
