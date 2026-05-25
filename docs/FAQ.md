# ❓ FAQ — 常见问题

> 按"上手 → 数据源 → 报告质量 → 高级"顺序排列。

---

## 🚀 上手 / 安装

### Q1：装好后第一次跑就报错"找不到 SKILL_ROOT"

skill 没装到搜索路径下。检查：
- Claude Code: `~/.claude/skills/house-hunter/`
- OpenClaw: `~/.agents/skills/house-hunter/`
- Gemini: `~/.gemini/extensions/house-hunter/`
- 开发模式: `~/workspace/tools/house-hunter/`

任一路径下有 `SKILL.md` + `scripts/` 目录即可。

### Q2：跑 status.py 报 `pyyaml/jinja2 缺失`

```bash
python3 scripts/setup.py
```
自动 pip install 缺失依赖。

### Q3：我**完全不想装** Chrome extension / 不想登链家，能用吗

**能！** 零依赖快速模式（lite mode）默认开启：
- 候选生成：自动 fallback 到百度地图 POI
- 建成年份：用 WebSearch 兜底（房产门户摘要）
- 配套：百度地图直接调

约 **80% 功能开箱即用**。装 extension 是**渐进增强**，不装也能用。

### Q4：我只想用 compare（PK 模式），不需要 search

完全可以。直接调：
```
/house-hunter 越秀滨海御城 vs 越秀滨海悦城
```
Opus 识别 compare 意图后**跳过 Python 候选生成**，纯走 WebSearch + 百度地图 + xhs。**1-3 分钟出报告**。

---

## 🗺️ 地图 API Key

### Q5：百度地图 API Key 申请总失败

最常见原因：**应用类型选错**。必须选「服务端」（`服务端`），不能选浏览器端 / iOS / Android SDK。

详细步骤见 [SKILL.md Step 0.A](../SKILL.md#step-0a-地图-key-引导关键面向-openclaw-普通用户)。

### Q6：百度地图限流了怎么办

skill 自动 fallback：
```
百度（5000/天） → 高德（100/天）→ 天地图（1 万/天）
```

只要 3 个之中有一个还能用就不影响主流程。**最强组合是 3 个都申请**（5 分钟/个，加起来 ~15,100 次/天免费）。

### Q7：天地图 vs 高德 vs 百度，哪个 POI 数据最好

**默认顺序：百度 > 高德 > 天地图**（按 POI 覆盖度）。
- 百度：商业类 POI（商场/餐饮）最全
- 高德：地铁/道路最准
- 天地图：政府公开数据，**配额最高**（1 万/天）但 POI 覆盖少

---

## 🏠 链家 / 贝壳数据

### Q8：bridge_server 显示 "extension not connected"

检查清单：
1. Chrome 是否开着？
2. `chrome://extensions/` 里 **Housing Bridge** 扩展是否启用（蓝色开关）？
3. 重启 bridge_server.py（在自己终端 Ctrl+C 再跑）
4. 重新加载扩展（chrome://extensions 点扩展卡片的「刷新」圆箭头）

### Q9：fetch 链家页面返回 CAPTCHA

链家反爬触发了。解决：
1. 在 Chrome 里**手动**打开报错的 URL（如 `https://sz.lianjia.com/xiaoqu/2123/`）
2. 过完滑块/拼图验证
3. 看到正常页面后回 Claude Code 继续

注意：链家把不同 path 当不同风控池：
- `/xiaoqu/{district}/` 列表
- `/xiaoqu/{id}/` 详情
- `/zufang/c{id}/` 挂牌
- `/xiaoqu/rs{name}/` 搜索

**任一 path 过 CAPTCHA 后，同 path 24h 不需要再过**，但其他 path 可能需要单独过。

### Q10：bridge_server 配额用完了（80/200）

跑 e2e 时短期消耗 bridge 配额（每个 community 多次 fetch）。处理：
1. **重启 bridge_server.py**（重新计配额）
2. **加 cache**：`housing_bridge.fetch_html` 已 24h 缓存，重复跑同小区不耗配额
3. **改 MAX_SESSION_FETCHES**：`scripts/housing_bridge_server.py` 顶部常量调大（默认 200）

### Q11：贝壳 ke.com 和链家 lianjia.com 选哪个

**贝壳是首选**（项目硬约束，详见 SKILL.md「数据源约束」节）。两者同公司同数据库，但 ke 是首选品牌：
- `rental.community_basic_info`：先 ke 后 lianjia
- `rental.community_rental_summary`：先 ke 后 lianjia
- 关键词搜：先 ke 后 lianjia

cookie 互通，登录任一即可。

---

## 📕 小红书 (xhs)

### Q12：xhs_health_probe.py 报"未登录"

在 Chrome 里手动打开 `https://www.xiaohongshu.com` 检查：
- 看到登录页 → 重新扫码登录
- 看到正常首页但 cli 还说未登录 → Chrome extension 没连上 bridge，重启 bridge_server.py + 刷新扩展

### Q13：xhs 调用全 0 结果

可能原因：
1. **账号风控**（多见）：在 Chrome 手动搜小红书看是否提示"请求太频繁"
2. **cookie 失效**：重新登录
3. **关键词太精准**：换更宽松词（如"洺悦府"代替"光明区电建地产洺悦府"）

恢复后**清 cache**：
```bash
rm ~/.local/share/house-hunter/cache/xhs_search-*.json
```

### Q14：xhs 账号被风控了能恢复吗

通常 24-48 小时自动解封。期间使用：
- `HOUSE_HUNTER_DISABLE_XHS=1` 临时禁用
- 仍能跑（POI/挂牌/WebSearch 都不受影响），只是缺居住口碑

### Q15：避免 xhs 风控的最佳实践

- 单 session 累计 xhs 搜索 ≤ 20 次（项目已强制限制）
- 不要短时间内对同一账号高频请求
- 让 xhs 自动节流（2-8s 随机 jitter，已内置）

---

## 📊 报告质量

### Q16：报告里建成年份全空

**Step 2.5 没生效**。LLM 应该在 Step 3 合成前用 WebSearch 兜底。Opus 应该自动做，如果没做：

手动让 LLM 重新检查：
```
/house-hunter 上面的报告里 X / Y / Z 三个小区缺建成年份，用 WebSearch 兜底补全后重新输出
```

详见 SKILL.md Step 2.5。

### Q17：候选小区不在我搜的区（如搜龙岗但出来罗湖小区）

链家 `/xiaoqu/longgang/` 列表混跨区（链家路径语义可能是关键词搜索）。解决：
1. skill 默认会跑**区过滤**（看 address 是否含目标区名）
2. 如果还是混区 → 用 area 模式（中心点 + 半径）
   ```
   /house-hunter 龙岗中心城为中心点 1km 内 2 房 5000
   ```

### Q18：报告说"小红书数据不可用"

如 Q13-Q15，xhs 暂时挂了。其他维度（POI / 挂牌 / WebSearch）不受影响。

### Q19：报告链接 `[name](#)` 全是死链

候选源是 baidu_map_poi 兜底（链家/贝壳没拿到对应小区），ID 不是真实数字 ID 所以没 url。如果想要真实链接：
1. 启用 Housing Bridge
2. 让 ke/lianjia 候选作为优先源
3. 或者 LLM 用 WebSearch 给每个名字搜对应的 ke 链接

---

## ⚙️ 高级 / 排查

### Q20：e2e 跑了 5 分钟没出报告

可能卡在：
1. **xhs Semaphore(1)**：xhs 全局串行，多个 community × 多 keyword 累积慢
2. **bridge fetch 超时**：默认 timeout=60s × 多次重试
3. **POI 校验超时**：百度地图 API 慢

处理：
```bash
# 看进程
ps aux | grep house_hunter.py
# 看实时日志（Python -u 不缓冲）
tail -f /tmp/hh_run.log
```

### Q21：如何只跑某一步（如只想跑 POI 校验）

Python 工具 API 可单独调用，详见 SKILL.md 顶部「📦 Python 工具 API 速查」：

```python
from sources import baidu_map
baidu_map.geocode("万象天成", "深圳市")
baidu_map.search_nearby("地铁站", lat, lng, 1000)
```

### Q22：缓存在哪？怎么清

```bash
ls ~/.local/share/house-hunter/cache/
```

按数据源命名（`rental_basic-`、`xhs_search-`、`housing_bridge_html-` 等）。失败的 None 缓存可能影响重跑，可手动清：

```bash
# 清所有
rm -f ~/.local/share/house-hunter/cache/*.json

# 仅清某源
rm -f ~/.local/share/house-hunter/cache/xhs_search-*.json
```

### Q23：报告保存在哪？

```
~/Documents/House-Hunter/
├─ {topic}-{YYYYMMDD}.md       ← markdown 报告
└─ {topic}-{YYYYMMDD}-raw.json ← 原始数据（含全部字段，可二次开发用）
```

### Q24：要把 skill 移到另一台电脑

复制整个 `~/.claude/skills/house-hunter/` 目录即可。需要重新做的：
- 装 Chrome 扩展（不能跨机器同步）
- 重新登 ke/小红书（Chrome cookie）
- 重新配置 API Keys（环境变量）

---

## 🐛 报 bug / 反馈

- GitHub Issues: https://github.com/kunhai1994/house-hunter/issues
- 邮件 / Slack：详见 README

报 bug 时附上：
1. 出问题时的 `/house-hunter` 输入
2. `python3 scripts/status.py --json` 输出
3. 报错日志（如有）
4. 期望 vs 实际行为
