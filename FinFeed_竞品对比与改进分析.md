# FinFeed 同类项目横向对比与改进分析

> 调研时间：2026-08｜范围：金融新闻聚合 + A 股行情监控 + 实时看板类开源 / SaaS 项目
> 目的：为 FinFeed 的六项优化（即时搜索 / 日期自动更新 / 日历分组 / 后台采集 / 看板重构 / 架构借鉴）提炼可落地方案。

## 一、可比项目概览

| 项目 | 技术 / 许可 | 定位 | 新闻聚合 | 行情/事实层 | 情感/LLM | 实时机制 | 调度/自动采集 |
|---|---|---|---|---|---|---|---|
| **AkShare** | Py/MIT | 数据接口库 | 部分 | ✅强 | ❌ | 轮询爬 | ❌ |
| **TuShare** | Py/积分 | 数据接口 | ❌ | ✅强 | ❌ | REST | ❌ |
| **qstock** | Py/MIT | 数据+可视化 | 文本 | ✅ | ❌ | 轮询 | ❌ |
| **Qlib** | Py/MIT | AI 量化平台 | ❌ | ✅(回测) | ✅ML | 批式 | 动态更新 |
| **FinGPT** | Py/MIT | 金融大模型 | ✅源 | ❌ | ✅LLM | 数据管道 | ❌ |
| **QUANTAXIS** | Py+Node/MIT | 全栈量化 | 爬虫 | ✅ | ❌ | HTTP/WS | ✅QASchedule |
| **GDELT** | 数据/免费 | 全球新闻事件库 | ✅全球 | ❌ | ✅Tone | 15min 分片 | 轮询 |
| **StockNews.ai** | SaaS/MCP | 预分析新闻信号 | ✅ | 部分 | ✅评分 | REST/WS | ✅ |
| **finboard** | Py/MIT | A股实时看板 | ❌ | ✅A股 | ❌ | 轮询 | ❌ |
| **WebStock** | Node/MIT | A股行情+DeepSeek | ❌ | ✅A股 | ✅ | 轮询 | ❌ |
| **daily_stock_analysis** | Py/MIT | 定时 LLM 选股 | ❌ | ✅ | ✅LLM | GitHub Actions | ✅ |
| **marketingdashboard** | Node/MIT | 行情大屏 | ❌ | ✅大屏 | ❌ | 轮询 | ❌ |
| **PanWatch** | Docker/MIT | 盯盘+告警 | ❌ | ✅ | ✅ | 轮询+告警 | ✅ |

**结论**：FinFeed 的独特定位在「新闻聚合 + 市场事实层 + 自托管看板」三位一体。上述开源项目多为单能力：AkShare/TuShare 只取数、Qlib/FinRL 只研究、GDELT/StockNews 只做新闻信号、finboard/WebStock 只做行情看板。最接近的是 QUANTAXIS（全栈）与 daily_stock_analysis（LLM+调度+推送），但二者均无完整「新闻+情感+事实层」组合。

## 二、对照六项优化的可借鉴方案

### 1. 即时新闻搜索 + 关键词高亮 + 空状态
- **借鉴 WebStock 的拼音/全拼/首字母模糊搜索**：让 A 股代码、中文名、拼音都能命中；后端 `/api/news` 已支持 `keyword`，前端再加拼音归一化将显著提升召回。
- **借鉴 StockNews.ai 的「可溯源 + 理由字段」**：搜索结果除标题外，展示来源与时间（已在 NewsRow 呈现），并可在详情层补充「为何命中」。
- **空状态三态区分**（本项目已落地）：无结果 / 数据源未采集 / 当日无相关新闻，分别给出不同提示与「清除筛选」动作，避免用户误判为系统故障。
- **高亮采用纯文本节点 + `<mark>`，绝不拼接 HTML**，规避 XSS（本项目 HighlightText 组件已采用此方案）。

### 2. 日期选择器默认今天 + 随时间自动更新
- **借鉴 PanWatch / TradingView 的「自动刷新开关」与 daily_stock_analysis 的定时触发**：日期默认 `today`，用户未手动改过时，定时（60s）重新校准为当前日期，跨午夜/跨交易日自动滚动（本项目 `useAutoToday` 已落地）。
- **非交易日降级**：若当日无数据，应在 UI 标注「最近交易日」并提供「跳到最新数据」入口（本项目行情页已加「最新数据 YYYY-MM-DD」按钮）。

### 3. 财经日历事件按类别分组
- **借鉴 qstock / 同花顺 / 东财的分类呈现**：按 `cal_type`（财经/股市/新股/全球）折叠分组，组头显示当日该类型事件数（本项目 `CalendarView` 已落地分组 + 组计数）。
- **进阶**：支持按类别筛选与跨类别时间轴；解禁/分红/龙虎榜等子类可再细分（后端 `category` 字段已具备，可后续下钻）。

### 4. 行情数据后台自动采集调度（本项目已落地）
- **直接借鉴 QUANTAXIS 的 QASchedule（后台任务调度 + 自动运维）+ Grafana+AKShare 定时写入**模式。
- **失败可见原则（daily_stock_analysis 强调）**：每个采集任务记录「上次成功时间 / 失败原因 / 数据日期」，避免把旧数据误当当日事实——本项目 `market/scheduler.py` 已为 universe/snapshot/bars 记录 `last_run.status/message/executed_date` 并暴露 `/api/market/autostatus`。
- **调度与 API 解耦**：调度 Worker 独立线程，按交易日时点（盘前 08:40 股票池、盘后 16:10 快照）每日一次，bars 默认关闭（限流保护），可用 `FINFEED_MK_AUTO=0` / `FINFEED_MK_AUTO_BARS=1` 调控。

### 5. 看板重构 + 缺失数据回填（本项目已落地）
- **借鉴 marketingdashboard 的「一屏大屏 + 模块卡片」与「缺失即占位」**：卡片显式标注「采集中 / 暂缺 / 源异常」，用「—」或最近可用值占位，而非留白或报错。
- **补全 API 已有但前端未用的数据**：`/api/stats` 长期提供 `time_trend`（24h 按小时新闻量）、`importance_distribution`（重要性分级）、`category_stats`（分类构成），本次看板新增「近 24h 趋势 / 重要性分布 / 分类分布」三张图，并把 KPI、状态条、洞察、明细重排为 5 层结构。

### 6. 整体架构
- **推荐「FastAPI 中台 + SSE/WebSocket 推送 + 调度 Worker + 轻量存储」** 解耦：采集、分析（情感/重要性）、推送三件事拆为独立 Worker（FinFeed 已用 SSE 推送 + 调度线程，方向一致）。
- **缓存与多源回退**：借鉴 Qlib 的缓存（`ExpressionCache` 思路）与 AkShare/efinance 的本地缓存+多源回退，可进一步降低重复计算与上游失效风险。
- **LLM 分析管线**：参考 FinGPT 的「五层数据管道 + RAG」做新闻分析管线，提升归因与报表质量。

## 三、本次已落地实现（代码侧）

| 模块 | 改动文件 | 要点 |
|---|---|---|
| 即时搜索 | `web/src/components/FilterBar.vue`、`NewsRow.vue`、`HighlightText.vue`（新）、`NewsView.vue` | 关键词输入即触发（350ms 防抖）；标题关键词高亮（XSS 安全）；搜索结果计数 + 上下文空状态 + 一键清除 |
| 日期自动更新 | `composables/useAutoToday.js`（新）、`CalendarView.vue`、`MarketView.vue` | 默认当日；未手动改时每 60s 校准，跨日自动滚动；行情页新增「最新数据」快捷跳转 |
| 日历分组 | `CalendarView.vue` | 按 cal_type（财经/股市/新股/全球）分组，组头带事件计数 |
| 后台自动采集 | `finfeed/market/scheduler.py`（新）、`ui/web_fastapi/app.py` | 交易日内定时自采（股票池 08:40 / 快照 16:10）；状态可查可开关（`/market/autostatus`、`/market/action?action=autocollect`）；失败可见 |
| 看板重构 | `DashboardView.vue` | 5 层结构（KPI/状态条/洞察三图/分布两图/健康明细）；补全 time_trend、importance_distribution、category_stats 三块缺失数据 |

## 四、后续建议（优先级）

1. **搜索召回增强**：引入拼音/首字母归一化与股票代码别名，复用 AkShare/efinance 思路做多源回退。
2. **采集失败告警**：把 `last_run` 的 error 状态通过现有 Webhook/订阅通道推送，落实「失败可见」。
3. **K 线自动补采**：bars 默认关闭以规避限流；可在休市时段（如 17:00–20:00）以更小 batches 增量开启。
4. **WebSocket 行情推送**：当前行情为请求/响应模式，可借鉴 TradingView/PanWatch 改为 WebSocket，进一步降低延迟。
5. **日历下钻**：基于已有 `category` 字段做子类筛选与时间轴视图，对齐东财/同花顺体验。

---
*主要来源：github.com/akfamily/akshare、blog.infoway.io、pypi.org（efinance/qstock）、quantlabsnet.com、ima.qq.com（FinRL/FinGPT/daily_stock_analysis）、github.cc/QUANTAXIS、gdeltproject.org、stocknews.ai、github.com/finvfamily/finboard、github.com/xujh1969/webstock、postgoo.com/marketingdashboard。*
