# FinFeed 架构评估报告

> 评估对象：`E:\VibeCoding\FinFeed`（实时金融新闻 + A 股行情监控平台）
> 评估日期：2026-09-04
> 代码基线：git `298` 次提交，单一作者，工作区干净
> 方法：AST 静态解析 + 运行时数据库实测 + 依赖环路检测 + 分层抽样代码审查

---

## 一、执行摘要

### 1.1 规模基线

| 维度 | 实测数据 |
|---|---|
| Python 后端 | 244 个 `.py` / 59,565 行 / 17 个顶层包 |
| 前端 | `web/src/` 134 个文件 / 33,930 行 / 97 个 `.vue` |
| API 端点 | 137 个（FastAPI） |
| 数据库 | 7 个 SQLite 文件，合计约 **1 GB** |
| 最大表 | `news` 300,880 行；`board_snapshots` 3,290,960 行 |
| 测试 | 134 个 Python 用例；前端 **0** |
| CI / Docker / pre-commit | **全部缺失** |

### 1.2 总体判断

FinFeed 是一个**功能完成度很高、但架构治理滞后于功能扩张**的单体系统。

值得肯定的地方很实在：解析器层用了策略模式（`core/parsers/base.py:44` 的 `BaseParser`）统一了 45 个异构数据源；去重引擎的四级设计（L1 URL → L2 标题哈希 → L3 SimHash → L4 时间窗）有明确的工程思考；批量写入全程 `executemany`（28 处）并用 `rowid` 边界精确回填，说明作者对 SQLite 有真实理解；前端把 97 个组件的网络请求全部收敛到单一 `api/client.js`，这比多数同类项目都干净。

但系统已经在向"大泥球"滑动，而且滑动的方向恰好是**最贵的那一条**：领域边界还没稳定，依赖拓扑就先失控了。15 个包级依赖环意味着**任何一次跨包改动都可能引发全仓范围的连锁反应**，而这正是项目继续演进的最大阻力。

### 1.3 三条最致命的问题

| # | 问题 | 为什么致命 |
|---|---|---|
| **1** | **依赖拓扑失控**：72 条包级边中检出 15 个环，最大环串联 7 个包，且 `storage` 反向依赖 `analysis`/`market` | 它不产生 Bug，但它让**每一个**后续改进都变贵。这是所有技术债里利息最高的一种 |
| **2** | **持久化无治理**：47 处 `CREATE TABLE` 散落 12 个文件，零迁移机制，5 条独立连接路径，无 `user_version` | Schema 无法安全演进。现在改一个表结构，等于赌所有旧库文件都能兼容 |
| **3** | **前后端契约裸奔**：137 个端点中 `response_model` 仅 5 处且**全为 `None`**（主动关闭校验）；前端 TypeScript 覆盖率 **0%** | 后端改一个字段名，前端静默炸在运行时。没有任何机器可校验的契约 |

---

## 二、系统全景

### 2.1 运行时形态

三个执行单元，物理隔离但逻辑上共享同一批 SQLite 文件，**彼此之间没有任何 IPC 或写入协调机制**：

1. **CLI 监控进程**（`finfeed/cli.py`）：asyncio 并发抓取，`Semaphore(FETCH_CONCURRENCY=10)` 限流，共享 `httpx.AsyncClient(max_connections=20)`，`asyncio.gather(return_exceptions=True)` 聚合。
2. **FastAPI Web 进程**：由 `cli.py:211` 以 `subprocess.Popen` 拉起独立 uvicorn（默认 `:8866`），与监控进程解耦。
3. **3+ 守护线程**：`market/scheduler.py`、`capital_dashboard/server.py`、`sector_minute/server.py` 各自 `threading.Thread(daemon=True)` + `while True: time.sleep(1)` 轮询。

全仓 **12 处 `while True`** 手写轮询调度，无持久化、无错过补偿、无分布式锁。服务重启或错过时间窗后，盘后任务（16:10 快照 / 16:20 涨停池 / 16:40 日线）是否补跑，取决于进程当时的存活状态。

### 2.2 部署形态

单体同进程部署：`ui/web_fastapi/app.py:700-702` 用 `StaticFiles` 挂载 `web/dist`，SPA 与 `/api` 共存于同一 FastAPI 应用，前后端同源。

---

## 三、模块划分

### 3.1 包职责与体量

| 包 | 文件 | 行数 | 职责 | 评估 |
|---|---|---|---|---|
| `core/` | 60 | 10,337 | 抓取 / 解析（45 个源解析器）/ 去重 / 管道 | 过度膨胀，`parsers/` 独占 8,358 行 |
| `market/` | 19 | 7,826 | 东财结构化事实层（涨停池 / 龙虎榜 / 日线 / 两融） | `store.py` 单文件 1,803 行、20 条 DDL |
| `screener/` | 21 | 6,336 | 五维加权选股 + 回测 + ML | 相对自洽 |
| `llm/` | 15 | 5,357 | LLM 客户端 / 分析服务 / 报告持久化 | 与 `application` 双向依赖 |
| `f10/` | 26 | 4,476 | 同花顺 F10 资料 | **独立移植子应用**，98 次自引用，可独立起服 |
| `capital_dashboard/` | 15 | 3,017 | 通达信资金流大屏 | **自带 FastAPI app** |
| `analysis/` | 14 | 2,890 | 情感 / 重要性 / 关键词 / 交叉引用 | 与 `market` 双向依赖 |
| `integrations/` | 10 | 2,601 | easy-tdx + screener 适配层 | — |
| `storage/` | 5 | 2,121 | SQLite 主库 | **分层倒置的震中** |
| `ecal/` | 9 | 2,144 | 财经日历 | 自洽，不侵入 news 表 |
| `stock_monitor/` | 6 | 1,843 | 自选股监控 | — |
| `ui/` | 14 | 2,721 | FastAPI Web 层 | 主 app + 路由 |
| `application/` | 5 | 1,714 | 服务编排 | 与 `llm` 双向依赖 |
| `sector_minute/` | 5 | 1,514 | 板块分时 | 与 `capital_dashboard` **结构同构复制** |
| `alerts/` | 6 | 1,236 | webhook / 订阅推送 | — |
| `config/` | 5 | 1,052 | 源配置 + 全局 settings | 健康叶子包，但非唯一配置源 |
| `utils/` | 5 | 352 | time / hash / http / common | **健康叶子包**，零外部 import |

### 3.2 边界观察：隐约可见的 Bounded Context

按领域语义，系统其实存在 6 个相对清晰的上下文：

- **新闻采集（News Acquisition）** — `core/`
- **市场事实（Market Facts）** — `market/`
- **智能分析（AI Insight）** — `llm/` + `application/`
- **告警推送（Alerting）** — `alerts/`
- **选股研究（Screening）** — `screener/`
- **财经日历（Calendar）** — `ecal/`

问题在于：**这些上下文在代码里没有边界**。`core` 直接 import `alerts`，`storage` 直接 import `market`，`analysis` 与 `market` 互调。上下文之间既没有防腐层（ACL），也没有领域事件解耦，全部是直接的函数调用。

`capital_dashboard/` 与 `sector_minute/` 是结构级复制的典型——各有 `config/models/store/collector/server + create_router + start_refresh_worker + 自己的 index.html`，连 `app.py:162/187` 里"读 index.html 再 `replace('</head>', inject)`"的注入逻辑都抄了两遍。

---

## 四、依赖关系分析

### 4.1 量化结果（AST 全量解析）

- 包级依赖边：**72 条**
- 包级依赖环：**15 个**
- 代表性环路：

```
analysis → market → analysis                                    (2 包)
storage → analysis → storage                                    (2 包)
market → core → storage → market                                (3 包)
alerts → analysis → market → core → alerts                      (4 包)
market → core → alerts → stock_monitor → llm → storage → market (6 包)
analysis → market → core → alerts → stock_monitor → llm → storage → analysis  (7 包，最大环)
```

另有 `content_extractor ⇄ content_fetch` 模块级环，以及 `config/sources.py ⇄ config/article_sources.py` 配置层环。

### 4.2 依赖强度 Top 10

| 源 → 目标 | 次数 | 判断 |
|---|---|---|
| `core → utils` | 55 | 健康 |
| `core → storage` | 50 | 健康 |
| `core → config` | 21 | 健康 |
| `analysis → storage` | 16 | 健康 |
| `application → market` | 13 | 健康 |
| `market → storage` | 13 | 健康 |
| `ui → llm` | 11 | 健康 |
| `application → llm` | 10 | **反向**（llm → application 亦存在） |
| `integration → screener` | 10 | 健康 |
| `core → analysis` | 4 | **倒置**（core 应不感知 analysis） |

### 4.3 分层倒置的四个确凿点

| 位置 | 代码 | 问题 |
|---|---|---|
| `storage/database.py:344` | `from finfeed.analysis.importance import compute_importance` | 最底层存储调用上层分析算法 |
| `storage/database.py:1182` | `from finfeed.market import store as market_store` | 最底层存储调用行情层写入 |
| `core/pipeline.py:14-16` | 顶层 `from finfeed.analysis.{importance,sentiment,text_analyzer}` | 采集管道反向依赖分析层 |
| `core/pipeline.py:247` | `from finfeed.alerts.dispatcher import schedule_dispatch` | 采集管道反向依赖告警层 |

**成因**：四者均为**函数内延迟导入**——这不是设计，是补丁。配合 `finfeed/__init__.py:20-24`（import 期即拉起 httpx 与 DB 路径解析）与 `market/__init__.py:31-75`（105 行、12 个子模块、39 个符号再导出）的重 import 副作用，循环依赖被 import 时序掩盖而非解决。

### 4.4 为什么现状还能跑

因为 Python 的延迟导入给了足够的窗口。代价是：

- 无法做**静态依赖检查**（任何工具都会报环）
- 无法**单独测试** `storage`（import 它会连带拉起 `market`）
- 无法**独立替换**任一层（想换 Postgres，得拖着 `analysis` 和 `market` 一起）
- **ruff 门禁只开 `F/E/W/I`**，无 import 环检测，新环会静默积累

---

## 五、数据流

### 5.1 新闻主链路

```
config/sources.py          源定义（45+ 源，Tier 1/6/12 分档）
  ↓
core/fetcher.py:223        fetch_all_news（asyncio + Semaphore(10) + 共享 AsyncClient）
  ↓
core/parsers/*             BaseParser 策略模式（json 22 / html 15 / forum 7 / rss）
  ↓
core/pipeline.py:105       process_news_items（清洗 → 股票校验 → 情感 → 重要性）
  ↓
analysis/*                 sentiment / importance / text_analyzer
  ↓
core/dedup.py:60           DedupEngine 四级去重（URL → 标题哈希 → SimHash → 时间窗+关键词）
  ↓
core/pipeline.py:240       db_insert_news
  ↓
storage/database.py:1195   NewsDatabase（单类 1,104 行）
  ↓
ui/web_fastapi/shared.py:54  broadcast_new_news（SSE 双水位线）
  ↓
ui/web_fastapi/routers/*  137 个端点
```

### 5.2 数据模型现状

**没有统一的领域模型层**。实测分布：

| 形态 | 数量 |
|---|---|
| `@dataclass` | 42 |
| pydantic `BaseModel` | 14（**全部是 Request/Payload/Patch 入参模型，零响应模型**） |
| `NamedTuple` / `TypedDict` | 0 / 0 |
| 裸 `dict(sqlite3.Row)` | **主流** |

`row_factory = sqlite3.Row`，行情、涨停池、龙虎榜、资金流等核心实体**均无模型类**，一律 `dict(row)` 直接返回（`market/store.py:1017,1050,1549,1667...`）。模型定义碎片化在 `capital_dashboard/models.py`、`sector_minute/models.py`、`ecal/models.py`、`screener/config.py`、`storage/models.py` —— 5 套并列，除 `NewsItem` 外无共享。

---

## 六、优点：应当被保留的设计

批评要具体，肯定也要具体。以下几点在改进中**必须保留**：

1. **解析器策略模式**（`core/parsers/base.py:44`）——45 个异构信源统一到 `BaseParser` 接口，新增源的成本被压到最低。这是全仓最有价值的一个抽象。
2. **四级去重**（`core/dedup.py:60`）——L1→L4 逐级降噪，且对 UGC/低优先级转载源做了豁免，保留独立时间线。这是有真实工程判断的设计，不是照搬。
3. **批量写入纪律**——671 处 SQL 中 `executemany` 占 28 处（18 处在 `market/store.py`），**全仓未发现循环内逐条 insert**。插入用 `rowid` 边界精确回填（`database.py:472-474`），考究。
4. **前端 API 单出口**——97 个 `.vue` 文件中 `axios`/`fetch(` 命中 **0 处**，唯一出口是 `web/src/shared/api/client.js`（统一 `ApiError` 归一化 + GET 错误重试 2 次 + 常规/长任务双超时 20s/120s）。
5. **自建设计系统**——`web/src/ui/` 24 个组件 + 31 KB `DESIGN_SYSTEM.md`，无第三方 UI 库却保持了视觉一致性。
6. **工程卫生良好**——无裸 `except:`、被注释掉的死代码仅 1 处、仓库无敏感文件入库（521 个已跟踪文件中无 `.log`/`.db`/`.env`）、提交信息规范（Conventional Commits）。

---

## 七、技术债务清单

### P0 — 阻塞演进

| ID | 问题 | 证据 | 影响 |
|---|---|---|---|
| P0-1 | **15 个包级依赖环** | AST 检测，最大环 7 包 | 任何跨包改动都可能引发连锁反应；无法独立测试/替换任一层 |
| P0-2 | **`storage` 分层倒置** | `database.py:344`、`:1182` | 存储层无法独立于业务演进；换 DB 引擎不可能 |
| P0-3 | **无 schema 版本管理** | 全仓零 `user_version`/`alembic`；47 处 `CREATE TABLE` 散落 12 文件 | Schema 无法安全演进，改表结构靠赌 |
| P0-4 | **5 条独立 SQLite 连接路径** | `storage/database.py:54`、`screener/*` 用 `self._path`、`llm/cleanup.py:96` 硬编码相对路径 `finfeed/news_monitor.db` | 配置不一致；`cleanup.py` 的路径 **CWD 敏感**，工作目录一变就操作错库 |
| P0-5 | **API 响应零契约** | 137 端点，`response_model` 5 处且全为 `None` | 前后端无机器可校验契约 |

### P1 — 显著影响质量与性能

| ID | 问题 | 证据 | 影响 |
|---|---|---|---|
| P1-1 | **`news` 表 22 个索引，约 12 个冗余** | `idx_pubts` ≡ `idx_pubts_id` ≡ `idx_publish_ts`（三份同定义）；`idx_source_ts` ≡ `idx_source_pubts`；`idx_fav_ts` ≡ `idx_fav_pubts`；`idx_source`/`idx_favorite` 被复合索引左前缀覆盖 | 每次写入维护 22 个 B-tree；索引/FTS 放大 2.4×（payload 284 MB → 文件 663 MB） |
| P1-2 | **`board_snapshots` 329 万行零索引** | `PRAGMA index_list` 返回空，286 MB | 资金流大屏查询必然全表扫描 |
| P1-3 | **孤儿表 `event_stock_link`** | 83,718 行 / 23.7 MB，代码零引用 | 死数据无人治理 |
| P1-4 | **旁路连接 + 每次调用执行 DDL** | `capital_dashboard/persist.py:34-48`：`sqlite3.connect()` 无 WAL 无 busy_timeout，且 `save_boards()` 每次执行 `CREATE TABLE IF NOT EXISTS` | 绕开统一治理；高频写入路径上有无谓 DDL 开销 |
| P1-5 | **N+1 扇出查询** | `market/store.py:1653-1714` `get_stock_profile()` 串行执行 **10 条 SELECT** | 单只股票详情的响应延迟是单查询的 10 倍 |
| P1-6 | **`self._lock` 定义后从未使用** | `database.py:38` 声明，全文件无 `with self._lock` | 统计缓存读写竞态（`:1028` 读 / `:1108` 写均无同步） |
| P1-7 | **`busy_timeout`(5s) < `connect(timeout=15)`** | `database.py:64` vs `:54` | 锁等待上限被 5s 截断，长事务易抛 `database is locked`，且全仓无重试 |
| P1-8 | **前端 0% TypeScript、0 测试** | `web/src/` 无 `.ts`/`.tsx`；无 vitest/jest | 与后端 134 用例形成悬殊反差 |
| P1-9 | **6 个超 1200 行巨石视图** | `ScreenerView.vue` 1945、`MarketView.vue` 1620、`SectorMinuteView.vue` 1415、`StockMonitorView.vue` 1389、`ThsLimitUp.vue` 1350、`EasyTdxView.vue` 1299 | TOP 10 组件占 `.vue` 总量 44% |
| P1-10 | **CORS 全开** | `app.py:251-256` `allow_origins=["*"]` | 生产为同源部署**不需要** CORS；本地 8866 全开意味着任意恶意网页可读取自选股与 LLM 配置 |
| P1-11 | **DEV 直连绕过 Vite proxy** | `runtime.js:6` DEV 走 `http://127.0.0.1:8866/api` 绝对 URL，使 `vite.config.js:31-45` 精心调优的 `/api` proxy **完全不生效** | proxy 中针对 Windows IPv6 / uvicorn keep-alive 半关闭 / ECONNRESET 的修复是死代码；注释与真实链路不符 |

### P2 — 累积性债务

| ID | 问题 | 证据 |
|---|---|---|
| P2-1 | 671 处裸 SQL 散落 36 文件，无 Repository 层 | `market/store.py` 129 处、`storage/database.py` 65 处、`llm/config.py` 28 处 |
| P2-2 | 配置 6 分天下 | `config/settings.py` + `capital_dashboard/config.py` + `sector_minute/config.py` + `screener/config.py`(545 行) + `llm/config.py`(513 行) + `f10/ths_config.py`；`market/scheduler.py:45` 直接 `os.environ.get` 绕过 settings |
| P2-3 | DB 文件写在源码包内 | `settings.py:42` 用 `dirname(dirname(abspath(__file__)))` → `finfeed/news_monitor.db`（663 MB） |
| P2-4 | `cli.py` 混入 250 行进程管理 | `_force_kill_tree:514`、PID 锁文件；859 行文件承担 5 类职责 |
| P2-5 | 12 处手写 `while True` 调度 | 无持久化、无错过补偿 |
| P2-6 | 无 CI / Docker / pre-commit | `scripts/ui_audit.py` 等质量脚本无人自动执行 |
| P2-7 | 根目录 4 个硬编码绝对路径的临时诊断脚本 | `_diag_hot.py`、`_diag_monitor.py`、`_diag_stocks.py`、`_verify_match.py`，内含 `E:\VibeCoding\FinFeed\...` |
| P2-8 | 类型注解覆盖不足 | 入参注解率 56.8%，返回注解率 83.5% |
| P2-9 | 过时文档 | `pyproject.toml:28` 与 `app.py:88` 仍称"双轨并行"，实际 legacy 已在 `b8f42c3` 退役 |
| P2-10 | 磁盘失控 | `logs/` 409 MB + `finfeed/news_monitor.db` 663 MB；`.git` 162 MB（含 36 张历史截图） |
| P2-11 | `except Exception` 达 511 处，部分静默吞异常 | `app.py:161/186` 模块降级、`pipeline.py:67` 吞掉算分异常 |

---

## 八、架构改进方案

### 设计原则

在给方案之前，先明确三条判断准则——这决定了方案的选择：

1. **单人项目，架构的第一目标是"三个月后自己还敢改"，不是"理论上最优"。**
2. **领域边界未稳定时，不做分布式拆分。** 当前 15 个依赖环恰恰证明边界还在变。
3. **先冻结、再收敛、最后重构。** 直接大重构会把"能跑的系统"变成"跑不起来的系统"。

---

### 方案 A：架构护栏——用 Import Linter 冻结现状（推荐指数 ★★★★★）

**目标**：阻止依赖环继续扩大，把架构腐化从"人治"变成"法治"。

**做法**：
1. 引入 `import-linter`，在 `pyproject.toml` 定义分层契约：

```toml
[tool.importlinter]
root_package = "finfeed"

[[tool.importlinter.contracts]]
name = "分层依赖：上层可依赖下层，禁止反向"
type = "layers"
layers = [
    "finfeed.ui",
    "finfeed.application",
    "finfeed.core:finfeed.market:finfeed.analysis:finfeed.llm:finfeed.alerts:finfeed.screener:finfeed.ecal:finfeed.stock_monitor",
    "finfeed.storage",
    "finfeed.utils:finfeed.config",
]

[[tool.importlinter.contracts]]
name = "storage 必须是叶子依赖"
type = "forbidden"
source_modules = ["finfeed.storage"]
forbidden_modules = ["finfeed.analysis", "finfeed.market", "finfeed.core",
                     "finfeed.ui", "finfeed.application", "finfeed.llm", "finfeed.alerts"]
```

2. 现有 15 个环**先全部登记进 `ignore` 白名单**，让 CI 变绿；每解一个环就从白名单划掉一条。
3. 接入 CI（方案 F）。

**预期收益**：
- 新环零增长——这是**唯一**能在单人项目里长期生效的架构约束
- 白名单本身成为一份"技术债台账"，解环进度可量化
- 成本极低（半天），不触碰任何业务代码，零回归风险

**适用场景**：所有阶段。这是**应当第一个做**的方案。

**代价**：初期白名单较长，需要纪律去逐步消化。

---

### 方案 B：切断 `storage` 反向依赖——依赖倒置（推荐指数 ★★★★★）

**目标**：让 `storage` 回到最底层，成为真正的叶子包。这是解环的第一刀，也是收益最大的一刀。

**做法**：

1. **处理 `database.py:344` 的 `compute_importance`**——改为**调用方注入**：

```python
# finfeed/storage/ports.py（新增，纯 Protocol 定义，零依赖）
from typing import Protocol
class ImportanceScorer(Protocol):
    def __call__(self, title: str, content: str, source: str) -> int: ...

# finfeed/storage/database.py
class NewsDatabase:
    def __init__(self, ..., scorer: ImportanceScorer | None = None):
        self._scorer = scorer
    # 删除 :344 的延迟导入，改为 self._scorer(...) if self._scorer else 默认值
```

在装配点（`core/pipeline.py` 或 `application/`）注入 `finfeed.analysis.importance.compute_importance`。**依赖方向反转**：`storage` 不再知道 `analysis` 的存在，`analysis` 通过端口适配 `storage`。

2. **处理 `database.py:1182` 的 `market_store`**——这段是"写新闻时顺带更新市场表"的耦合，应上移到 `application/` 的用例函数：

```python
# finfeed/application/news_ingest.py
def ingest_news(items, db, market_store):
    db.insert_news(items)
    market_store.record_news_refs(items)   # 由编排层显式调用，而非 storage 内部偷偷调用
```

**预期收益**：
- `storage` 变成纯叶子依赖，可独立测试（不再连带拉起 `market`）
- 消除 `storage → analysis → market → core → storage` 等 **5 个环**
- 为未来替换存储引擎（如 Postgres 分库）扫清结构性障碍

**代价**：需要修改调用点，估计 10-20 处。但每处都是机械改动，且有测试可守。

**适用场景**：P0，紧随方案 A 之后。只在"打算长期维护这个项目"时值得做——如果项目只是短期使用，可以只做方案 A。

---

### 方案 C：持久化治理——统一连接 + Schema 版本化（推荐指数 ★★★★★）

**目标**：消灭 5 条独立连接路径，让 schema 可以安全演进。

**做法**：

1. **唯一连接出口** `finfeed/storage/connect.py`：

```python
@contextmanager
def get_connection(db_key: str) -> Iterator[sqlite3.Connection]:
    path = settings.resolve_db_path(db_key)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")   # 与 timeout 对齐，不再被 5s 截断
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
```

强制所有模块（含 `capital_dashboard/persist.py`、`llm/cleanup.py`）走这个出口。

2. **Schema 版本化**：引入 `PRAGMA user_version` + `finfeed/storage/migrations/` 目录（`0001_init.sql`、`0002_xxx.sql`）。启动时按版本号顺序执行，取代现在的 47 处内联 `CREATE TABLE` 与 metadata KV 哨兵（`database.py:185` 的 `dedup_hashes_calculated_v1`）。

3. **DB 路径外移**：从 `finfeed/` 源码包移到项目根 `var/` 或 `~/.finfeed/`，通过 `FINFEED_DATA_DIR` 配置。

**预期收益**：
- Schema 可演进、可回滚、新机器可一键初始化
- 消灭 `database is locked` 隐患与 CWD 敏感路径
- DB 不再混在源码包，消除误入库风险

**代价**：中等。需要一次性的存量迁移脚本。

**分阶段建议**：
- C1（立即）：统一连接出口 + 修 `persist.py` 与 `cleanup.py` 两条野连接
- C2（本季度）：新表全部走 migrations；存量 47 处**先冻结**不搬
- C3（下一阶段）：存量表逐步迁入迁移脚本

---

### 方案 D：索引瘦身与热点表治理（推荐指数 ★★★★★）

**目标**：用最低风险换取最直接的读写性能提升。

**做法**：

1. **`news` 表 22 索引 → 保留 10 个**。删除清单（已在 300,880 行实测库上确认定义完全重复）：

```
删除 idx_pubts, idx_pubts_id        （与 idx_publish_ts 三份同定义，保留其一）
删除 idx_source_ts                  （≡ idx_source_pubts）
删除 idx_fav_ts                     （≡ idx_fav_pubts）
删除 idx_source, idx_favorite       （被复合索引左前缀覆盖）
删除 idx_sentiment, idx_importance  （被 idx_sent_pubts / idx_imp_pubts 覆盖）
```

2. **`board_snapshots` 加索引 + 归档**：
   - 加 `(ts, code)` 复合索引，消灭 329 万行全表扫描
   - 按周归档，只保留 30 天（这是时序快照，历史价值随时间衰减）

3. **删除孤儿表 `event_stock_link`**（8.3 万行，代码零引用，释放 23.7 MB）

**预期收益**：
- 每次新闻写入少维护 12 个 B-tree，写入吞吐显著提升
- 大屏查询从全表扫描变为索引扫描
- 预计释放 300 MB+ 磁盘

**代价**：低。删索引前用 `EXPLAIN QUERY PLAN` 核对高频查询即可。

**适用场景**：立即执行。**在所有方案中 ROI 最高、风险最低**。

---

### 方案 E：OpenAPI 契约化 + 前端渐进 TS（推荐指数 ★★★★☆）

**目标**：消灭"改后端不知道前端哪里会炸"。

**做法**：

1. **后端补响应模型**（分批，先 Top 30 高频端点）：

```python
# 现状（news.py:135）
@router.post("/api/favorite", response_model=None)

# 目标
class FavoriteResponse(BaseModel):
    id: int
    is_favorite: bool
@router.post("/api/favorite", response_model=FavoriteResponse)
```

2. **前端类型生成**：`openapi-typescript` 从 FastAPI 的 `/openapi.json` 生成 `web/src/api/schema.d.ts`，CI 中校验是否有 drift。

3. **前端渐进 TS 化**（顺序很重要）：
   - 第一步：`allowJs: true` 起步，先转 `api/` 与 `store/`（约 900 行）
   - 第二步：转 `composables/` 与 `ui/`
   - 第三步：视图层最后（且应在方案 G 拆分巨石之后）

**预期收益**：
- 后端字段改名时，前端 `tsc` 直接报错，而非运行时白屏
- OpenAPI 从"仅供参考"变成可消费的契约
- 前端 IDE 补全与重构能力大幅提升

**代价**：137 端点全量补模型工作量大。**先做 Top 30 是务实折中**——不要追求 100% 覆盖。

**不推荐的做法**：立刻对 33,930 行前端做 `--strict` 全量 TS 迁移。0 测试 + 0 类型的基础上一刀切，会陷入类型地狱且阻塞所有功能开发。

---

### 方案 F：CI 门禁（推荐指数 ★★★★★）

**目标**：把质量检查从"人记着跑"变成"不跑就合不进去"。

**做法**：GitHub Actions 四道门禁：

```yaml
- ruff check .                    # 现有 F/E/W/I 规则
- lint-imports                    # 方案 A 的架构契约
- pytest -q                       # 134 个存量用例
- cd web && npm run build         # 前端构建不破
```

**预期收益**：半天工作量，永久收益。当前项目已有 `.ruff_cache/`（说明本地跑过 ruff）但无任何自动化，质量完全依赖记忆。

**代价**：几乎为零。

**适用场景**：立即做。**这是所有其他方案能够持续生效的前提**。

---

### 方案 G：前端巨石拆分（推荐指数 ★★★☆☆）

**目标**：把 6 个 >1200 行视图降到可维护规模。

**做法**：按"视图 = 编排，逻辑下沉 composable，展示下沉子组件"三层拆分：

```
ScreenerView.vue (1945) → views/ScreenerView.vue (编排, ~300)
                        → composables/useScreenerFilter.ts (筛选逻辑)
                        → composables/useScreenerResult.ts (结果处理)
                        → components/screener/FilterPanel.vue
                        → components/screener/ResultTable.vue
```

**预期收益**：单文件可理解性提升；为后续 TS 化（方案 E）创造条件。

**代价**：中等。且**拆分必须先于 TS 化**——否则等于给一坨泥球加类型注解。

**适用场景**：在方案 E 第三步之前做。优先级低于 A-F，因为前端当前"能跑且视觉一致"，不是阻塞项。

---

### 方案 H：调度器收敛（推荐指数 ★★★☆☆）

**目标**：消灭 12 处手写 `while True`。

**做法**：统一到 `finfeed/scheduling/`，保留手写实现但集中管理，增加：
- 上次运行时间持久化（存 DB）
- 错过补偿：进程启动后检查时间窗，若当日该时段任务未执行则补跑
- 单一调度入口，取代 `market/scheduler.py`、`capital_dashboard/server.py`、`sector_minute/server.py` 各自轮询

**预期收益**：服务重启后盘后任务不再靠运气；调度逻辑可测试。

**代价**：中等。建议先集中、后增强，不要一步到位上 APScheduler/Celery（会增加依赖与部署复杂度，与单机定位不符）。

---

### 明确的反面建议：不要做的事

作为架构评估，指出"不该做"和指出"该做"同样重要：

**1. 不要拆微服务。**
单机部署、SQLite 单文件、单人维护——拆服务只会把函数调用变成网络调用，把本地事务变成分布式事务，把 15 个依赖环变成 15 个跨服务契约。更关键的是：**15 个环恰恰说明领域边界尚未稳定**。在边界不清时拆服务，是最贵且最难逆转的错误。正确顺序是：先解环（方案 B），边界自然浮现，届时再评估。

**2. 不要急着引入 SQLAlchemy / Alembic。**
1 GB 单文件 SQLite 的瓶颈在索引写法（22 个冗余索引）和查询模式（N+1），**不在 ORM 层**。引入 ORM 会让现有 671 处手写 SQL 变成"两套写法并存"，反而更乱。建议路径：方案 C（连接治理）→ 方案 D（索引）→ 观察 → 若确有必要再评估 ORM。

**3. 不要全量 TS 化。**
见方案 E 的说明。渐进式，先 API 层。

**4. 不要一次性重写 `market/store.py`（1,803 行）。**
大爆炸重写在单人项目里等于自杀。正确做法是：先加测试锁住行为，再按聚合切成 `market/repositories/{limitup,billboard,moneyflow,dailybar}.py`。

---

## 九、实施路线图

按"**先冻结、再止血、后重构**"的顺序，每个阶段都可独立交付、独立回滚。

### 第一阶段：冻结与止血（1-2 周）

| 序 | 方案 | 交付物 | 风险 |
|---|---|---|---|
| 1 | F — CI 门禁 | `.github/workflows/ci.yml`（ruff + pytest + build） | 极低 |
| 2 | A — Import Linter 契约 | `pyproject.toml` 分层契约 + 15 环白名单 | 极低 |
| 3 | D — 索引瘦身 + 孤儿表清理 | 迁移脚本 + 释放 300 MB | 低 |
| 4 | C1 — 统一连接出口 | `storage/connect.py` + 修复 2 条野连接 | 低 |
| 5 | 清理临时脚本与日志 | 删除根目录 4 个 `_*.py`；归档 `logs/` | 极低 |

**阶段目标**：CI 变绿，架构腐化被冻结，写入性能提升，磁盘释放 300 MB。**不改动任何业务逻辑**。

### 第二阶段：解环与契约（3-5 周）

| 序 | 方案 | 交付物 |
|---|---|---|
| 6 | B — 切断 storage 反向依赖 | `storage/ports.py` + 装配点注入；消灭 5 个环 |
| 7 | E1 — Top 30 端点补响应模型 | pydantic Response 模型 + OpenAPI 生成 |
| 8 | C2 — 新表走 migrations | `storage/migrations/` + `user_version` |
| 9 | E2 — 前端 API 层 TS 化 | `api/` + `store/` 转 `.ts` + `schema.d.ts` 生成 |

**阶段目标**：`storage` 成为叶子包；前后端有机器可校验契约；新表 schema 可演进。

### 第三阶段：结构收敛（1-2 月，可与功能开发并行）

| 序 | 方案 | 交付物 |
|---|---|---|
| 10 | G — 前端巨石拆分 | 6 个巨石视图降到 300-400 行 |
| 11 | H — 调度器收敛 | `finfeed/scheduling/` + 错过补偿 |
| 12 | P2-2 — 配置收口 | 6 个 config 合并为 settings 树；CORS 收窄 |
| 13 | P2-1 — Repository 层 | 按聚合收敛 671 处裸 SQL |
| 14 | C3 — 存量表迁入迁移脚本 | 47 处 `CREATE TABLE` 收敛 |

**阶段目标**：边界清晰、可测试、可持续演进。

---

## 十、建议的架构决策记录（ADR）

落地时应为以下决策补 ADR，重点是记录**为什么**而非**做了什么**：

- **ADR-001**：采用 Import Linter 分层契约而非人工 Code Review 约束架构
- **ADR-002**：继续使用模块化单体，不拆微服务（记录反面理由：边界未稳定 + 单人维护）
- **ADR-003**：持久化继续用原生 sqlite3，不引入 ORM（记录触发重新评估的条件）
- **ADR-004**：前端渐进式 TS 化，顺序为 api → store → composables → views
- **ADR-005**：数据目录从源码包外移至 `var/` 或 `~/.finfeed/`

---

## 十一、结语

FinFeed 最值得肯定的是：它在**没有架构约束的情况下**，依然长出了一批正确的局部设计——`BaseParser` 策略模式、四级去重、`executemany` 纪律、前端 API 单出口。这说明作者有扎实的工程直觉。

但工程直觉能支撑 5 万行，支撑不了 15 个依赖环。当前的 FinFeed 正处在那个典型的临界点上：**继续加功能还是先还债**。

本报告的建议是：**先花 1-2 周做第一阶段**（CI + 架构契约 + 索引瘦身 + 连接治理）。这一阶段不触碰任何业务逻辑，风险极低，但能同时做到三件事——冻结债务增长、释放 300 MB 磁盘、让后续所有重构都有安全网。

此后按第二阶段推进解环与契约。第三阶段的结构收敛可以与日常功能开发并行，不必停工。

**最不该做的，是在依赖环未解、测试覆盖不足的情况下，启动任何形式的大规模重写。**

---

*本报告基于 2026-09-04 的代码基线。所有数据均来自 AST 静态解析与运行时数据库实测，具体证据已标注文件路径与行号。*
