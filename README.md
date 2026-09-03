# FinFeed · 实时金融新闻与 A 股市场监控系统

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Version](https://img.shields.io/badge/version-2.1.0-orange.svg)

FinFeed 是一套**模块化、可扩展的实时金融资讯与行情监控平台**，同时覆盖「新闻文本层」与「市场事实层」两条数据主线，面向个人投资者、量化研究员与舆情分析场景。系统以高并发抓取、多级智能去重、情感/重要性分析为核心，并通过 FastAPI + Vue 3 的现代 Web 仪表盘提供实时看板、历史检索、财经日历、大模型增强分析与 A 股盘后事实报表。

## 目录

- [项目简介](#项目简介)
- [功能特性](#功能特性)
- [技术架构](#技术架构)
- [环境依赖](#环境依赖)
- [安装步骤](#安装步骤)
- [配置说明](#配置说明)
- [快速上手](#快速上手)
- [Web 界面与 API](#web-界面与-api)
- [目录结构](#目录结构)
- [开发指南](#开发指南)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 项目简介

FinFeed 并非单一的新闻聚合器，而是将**非结构化新闻**与**结构化市场事实**统一在同一套管道中：

- **新闻文本层（`core/` + `analysis/`）**：从 45+ 公开财经信源实时抓取快讯、公告、股吧热帖与热搜，经过解析、多级去重与情感/重要性分析后入库。
- **市场事实层（`market/` + `ecal/`）**：以东方财富数据中心为底座，构建可校验的 A 股事实——行情宽度、涨停/跌停/炸板池、资金流向、龙虎榜、日线、两融、业绩预告、新股日历，并通过 `analysis/crossref.py` 与新闻层基于股票代码关联交叉分析。
- **智能分析层（`llm/`）**：集成任意 OpenAI 兼容大模型，对新闻做增强摘要、归因与报表生成。

系统默认在本地运行（SQLite 存储，无外部服务依赖），适合自托管、长周期积累与二次开发。

> **数据源完整性提示**：本项目依赖公开网页/接口抓取。数据源结构与反爬策略会变化，若某数据源持续失败，请查看运行日志（`logs/finfeed.log` 或 `finfeed.log`）中的健康监控与断路器信息。

---

## 功能特性

**多源实时抓取**
- 覆盖 40+ 信源：新浪财经、财联社、金十数据、东方财富、同花顺（原创/财经/论股堂/股吧）、华尔街见闻、格隆汇、巨潮公告、21 经济网、第一财经、新华财经、集思录等。
- **分级调度**：按信源时效性分档（Tier 1/6/12）错峰抓取，兼顾时效与请求压力。
- **并发抓取 + 离线补抓**：基于 `asyncio` 的并发 fetcher，附带断线后的分级补抓与断路器保护。

**智能分析与去重**
- 情感分析（新闻/论坛/研报/快照多模型）、重要性评估、关键词与股票名抽取、跨源关联。
- **四级去重**：L1 URL 精确 → L2 标题哈希 → L3 SimHash 语义 → L4 时间窗 + 关键词重合。
- 论坛类 UGC 与低优先级转载源可豁免跨源语义去重，保留独立时间线。

**A 股市场事实层**
- 盘后快照（全市场资金流 + 市场宽度）、涨停/跌停/炸板池、龙虎榜、日线回补、两融、业绩预告、新股日历。
- 涨停归因报表（`--market report`）与市场状态告警（`--market alerts`），服务于收盘复盘场景。

**财经日历**
- 整合东方财富四大日历（财经日历中心 / 股市日历 / 新股申购 / 全球经济），按日增量同步并带 TTL 缓存。

**大模型增强（AI 分析）**
- 支持任意 OpenAI 兼容服务：OpenAI、DeepSeek、阿里通义千问、月之暗面 Kimi、智谱 GLM、硅基流动、火山方舟豆包、本地 Ollama / LM Studio 等。
- 供应商配置持久化于本地库，API Key 仅在接口返回掩码值，不回传前端。
- 三类报告：复盘简报（资讯 × 市场事实包交叉复盘）、个股深度（行情/资金/龙虎榜事实包 + 关联资讯）、舆情研判（舆情热度 + 市场情绪聚合）。
- 结论可溯源：报告关键结论标注 `[编号]` 引用，阅读器提供「引用资讯对照表」一键回链原文。
- 事实包组装器（`finfeed/llm/context.py`）：涨停/连板天梯/题材风口/资金流/龙虎榜/两融/财经日历/舆情热度由程序确定性采集注入，模型只做归因叙述、不负责计数。
- 对话增强：@标的真正注入个股事实包上下文，`/复盘` 斜杠命令直接提交生成任务，自由问答按问题关键词检索相关资讯（含正文摘要）。
- 任务队列：运行中任务之外支持排队（上限 5 个），失败任务落库并可跨重启重试；分析默认值服务端持久化（跨设备共享）。

**Web 仪表盘与推送**
- FastAPI 单轨：新版 Vue 3 + Vite SPA（8866）由 FastAPI 同源托管；SSE 广播通道由 `ui.web.shared` 承载，旧版 `server.py` 已退役。
- 实时 SSE 增量推送、情感趋势、收藏、全文检索、历史导出、LLM 报表导出。
- AI 分析报告生成支持 SSE 流式输出：REDUCE 汇总阶段逐段实时预览（`GET /api/llm/task/stream?id=<task_id>`，事件：stage / delta / reset / done），流式失败自动回退一次性生成保证结果完整。
- 完整 OpenAPI 文档（Swagger UI / ReDoc）。

**数据导出**
- 支持 JSON / CSV / Excel / Markdown 四种格式，可按日期范围筛选。

**告警与订阅**
- 基于订阅规则的 Webhook 推送（`alerts/`）。

---

## 技术架构

```
┌─────────────────────────────────────────────────────────┐
│                     UI Layer                            │
│  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │   Web Dashboard │  │        Terminal Output      │  │
│  │ (Vue3 + FastAPI)│  │                             │  │
│  └────────┬────────┘  └─────────────────────────────┘  │
└───────────┼────────────────────────────────────────────┘
            │
            │  ┌────────────────────────────────────────────┐
            │  │               Web (FastAPI)               │
            │  │   SSE 推送 · REST API · 静态 SPA 托管      │
            │  └───────────────────┬───────────────────────┘
            │                      │
┌───────────▼────────────────────────────────────────────┐
│                    Core Layer                           │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────────┐  │
│  │ Monitor │→ │  Fetcher │→ │ Parser  │→ │ Pipeline │  │
│  │ Manager │  │(并发抓取) │  │(策略模式)│  │(处理管道)│  │
│  └─────────┘  └──────────┘  └─────────┘  └─────┬──────┘  │
│                                   ┌─────────────▼───────┐│
│                                   │    Dedup Service    ││
│                                   └─────────────────────┘│
└───────────────────────────────┬─────────────────────────┘
                                │
        ┌───────────────────────┼────────────────────────┐
        │        Fact Layer     │     Analysis Layer      │
        │  market/  ecal/       │  analysis/  llm/        │
        └───────────┬───────────┴────────────┬───────────┘
                    │                         │
┌───────────────────▼─────────────────────────▼─────────────┐
│                  Storage Layer                          │
│  ┌─────────────────────────┐  ┌───────────────────────┐ │
│  │     SQLite Database     │  │       Exporter        │ │
│  │   (WAL · 多表事实模型)   │  │ (JSON/CSV/Excel/MD)   │ │
│  └─────────────────────────┘  └───────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

---

## 环境依赖

| 依赖项 | 版本要求 | 说明 |
|--------|----------|------|
| Python | **≥ 3.10** | 项目构建与运行环境 |
| Node.js | **≥ 18** | 仅前端开发/构建需要（Vite 5） |
| 操作系统 | Windows / Linux / macOS | 无特殊内核依赖 |
| 网络 | 可访问目标信源 | 抓取与行情接口需公网 |

**Python 运行时依赖**（由 `pyproject.toml` 统一管理）：

```
httpx, beautifulsoup4, lxml, rich, playwright,
openpyxl, fastapi, uvicorn, python-multipart, pydantic, pydantic-core
```

> **说明**：`pyproject.toml` 的 `[project.dependencies]` 是依赖的**唯一真相源**，`requirements.txt` 仅为其便捷镜像，二者需保持同步。推荐始终使用 `pip install -e .` 安装。

---

## 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/finfeed/finfeed.git
cd FinFeed

# 2. （推荐）创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. 以可编辑模式安装（与 pyproject.toml 依赖一致）
pip install -e .

# 4. 安装 Playwright 浏览器内核（用于绕过部分数据源反爬）
playwright install chromium

# 5. 构建前端（可选；若不构建，FastAPI 仅提供 API，不含前端页面）
cd web
npm install
npm run build        # 产出 web/dist，由 FastAPI 静态托管
cd ..
```

> 若仅需要 Web 界面预览、无需浏览器渲染监控，可跳过第 4 步，使用 `--web-only` 启动（见下文）。

---

## 配置说明

### 1. 环境变量（前缀 `FINFEED_`）

所有核心配置集中位于 `finfeed/config/settings.py`，并支持以 `FINFEED_` 前缀的环境变量覆盖：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `FINFEED_WEB_PORT` | `8866` | Web 仪表盘端口 |
| `FINFEED_INTERVAL` | `5` | 抓取间隔（秒） |
| `FINFEED_FETCH_CONCURRENCY` | `10` | 并发抓取数 |
| `FINFEED_DB_FILENAME` | `news_monitor.db` | 数据库文件名 |
| `FINFEED_DB_PATH` | 项目根目录 / 文件名 | 数据库完整路径 |
| `FINFEED_USE_WAL_MODE` | `true` | 启用 SQLite WAL 模式 |
| `FINFEED_LOG_LEVEL` | `INFO` | 日志级别（DEBUG/INFO/WARNING/ERROR） |
| `FINFEED_LOG_PATH` | 项目根 / `finfeed.log` | 日志文件路径 |

示例：

```bash
export FINFEED_WEB_PORT=9000
export FINFEED_INTERVAL=30
export FINFEED_LOG_LEVEL=DEBUG
```

### 2. 数据源配置

数据源定义在 `finfeed/config/sources.py`（基于 `NewsSource` 类）。新增或调整信源即修改该文件，详见[开发指南](#开发指南)。

### 3. 大模型（LLM）配置

LLM 供应商配置持久化于主库的 `llm_providers` 表，**推荐通过 Web 界面（设置 → LLM 供应商）或 REST API（`/api/llm/*`）填写**，无需手动编辑文件。内置预设包括 OpenAI、DeepSeek、通义千问、Kimi、智谱、硅基流动、火山方舟、Ollama、LM Studio 及自定义。API Key 以明文存于本地 SQLite，对外接口一律返回掩码值。

### 4. 日志

运行日志默认写入 `logs/finfeed.log`（同时保留于项目根的 `finfeed.log`），采用滚动切割（单文件 10 MB，保留 5 份）。

---

## 快速上手

### 启动实时监控

```bash
# Windows 一键启动：自动重建前端 web/dist → 安装缺失依赖 → 启动监控
scripts\start_monitor.bat

# 等效的手动步骤（macOS / Linux 可用）：
npm run build && python main.py

# 启动实时监控（默认 FastAPI 单轨：8866）
python main.py

# 自定义抓取间隔（每 60 秒）
python main.py --interval 60

# 只抓取一次后退出
python main.py --once

# 显式指定 Web 后端（FastAPI 单轨）
python main.py --web fastapi   # 默认：FastAPI 单轨(8866)；旧版 server.py 已退役
```

> 注意：`start_monitor.bat` 每次启动都会**先重建 `web/dist`**。前端源码更新后无需手动 `npm run build`——直接双击脚本即可，避免因 dist 过期看到旧界面（历史教训：曾因未重建 dist 导致生产界面停留在旧设计）。

### 无浏览器 / 仅预览界面

若运行环境无可用浏览器（Playwright 无法启动），可用 `--web-only` 仅启动 Web 服务，避开监控器稳定预览：

```bash
python main.py --web-only          # 仅 Web（8866），Ctrl+C 停止
```

### 数据导出

```bash
# 导出为 JSON（默认自动生成路径，可用 -o 指定）
python main.py --export json

# 导出为 CSV / Excel / Markdown
python main.py --export csv
python main.py --export excel
python main.py --export markdown

# 按日期范围导出
python main.py --export json --start 2024-01-01 --end 2024-01-31 --output news_202401.json
```

### A 股市场事实层

市场事实层通过 `--market` 子指令驱动（详见 `finfeed/market/__init__.py`）：

```bash
python main.py --market init        # 初始化事实层数据表
python main.py --market universe    # 同步股票池与板块成分
python main.py --market snapshot --date 2026-08-07   # 指定交易日盘后快照
python main.py --market bars --limit 250             # 日线历史回补（限量）
python main.py --market backfill    # 历史新闻与股票事实关联
python main.py --market calibrate   # 情感校准
python main.py --market report      # 涨停归因报表
python main.py --market alerts      # 市场状态告警
```

### 命令行参数一览

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--port PORT` | Web 仪表盘端口 | `8866` |
| `--interval N` | 抓取间隔（秒） | `5` |
| `--once` | 仅抓取一次后退出 | — |
| `--export {json,csv,excel,markdown,md}` | 导出格式 | — |
| `--output, -o PATH` | 导出文件路 | 自动生成 |
| `--start / --end DATE` | 导出日期范围 `YYYY-MM-DD` | — |
| `--market ACTION` | 事实层指令：`init`/`universe`/`snapshot`/`bars`/`backfill`/`calibrate`/`report`/`alerts` | — |
| `--date DATE` | 事实层所用交易日 | — |
| `--limit N` | `bars` 回补数量上限 | — |
| `--web {fastapi}` | Web 后端模式（FastAPI 单轨） | `fastapi` |
| `--web-only` | 仅启动 Web（不运行监控器） | — |

---

## Web 界面与 API

自 v2.1 起，Web 前端为 Vue 3 + Vite 构建的 SPA，由 FastAPI 同源单轨托管（8866）；SSE 广播通道由 `ui.web.shared` 承载，旧版 `server.py` 已退役。

| 端口 | 服务 | 说明 |
|------|------|------|
| `8866` | FastAPI + Vue SPA | 默认主入口，现代 SaaS 亮色风格 |

- **API 交互文档（Swagger UI）**：`http://127.0.0.1:8866/docs`（OpenAPI 在 `/openapi.json`）
- **交互式文档（ReDoc）**：`http://127.0.0.1:8866/redoc`
- **健康检查**：`http://127.0.0.1:8866/api/ping`
- 主要接口：`/api/flash`（快讯）、`/api/articles`（财经文章）、`/api/stats`、`/api/sentiment`（舆情）、`/api/search`、`/api/detail`、`/api/favorites`、`/api/export`、`/api/calendar/export`、`/api/llm/report/export`、`/api/events` 等。
- 注：原「新闻流」模块已拆分为「快讯」（`/api/flash`）与「财经」（`/api/articles`）两个独立模块，`/api/news` 已移除。
- 市场语义色沿用 A 股惯例：**红涨绿跌**。实际色值以 `web/src/styles/tokens.css` 为准（亮色 涨 `#e11d48` / 跌 `#059669`，暗色 涨 `#f43f5e` / 跌 `#10b981`），勿在业务代码中硬编码。
- 前端设计规范与已知技术债见 [`web/DESIGN_SYSTEM.md`](./web/DESIGN_SYSTEM.md)。

前端开发 / 重新构建：

```bash
cd web
npm install        # 安装依赖（vue / vue-router / pinia / axios / echarts / vite）
npm run dev        # 开发服务器（代理 /api → 8866，支持热更新，默认 5173）
npm run build      # 产出 web/dist，由 FastAPI 静态托管
```

> 若 `web/dist` 不存在，FastAPI 仅提供 API（不含前端页面）；需先执行 `npm run build` 生成前端。

---

## 目录结构

```
FinFeed/
├── finfeed/                    # 主包
│   ├── alerts/                 # 告警与订阅（Webhook / 订阅规则）
│   ├── analysis/               # 文本分析（情感/重要性/关键词/跨源关联）
│   ├── calendar/               # 财经日历（预留模块，当前为空）
│   ├── config/                 # 配置管理（settings / sources）
│   ├── core/                   # 核心业务（monitor / fetcher / parsers）
│   │   └── parsers/            # 解析器（策略模式）
│   ├── ecal/                   # 财经日历（东方财富四大日历）
│   ├── llm/                    # 大模型分析（多供应商兼容）
│   ├── market/                 # 市场事实层（A股快照/涨停归因/龙虎榜/日线）
│   ├── storage/                # 数据持久化（database / exporter / models）
│   ├── ui/                     # 用户界面
│   │   ├── web/                # 共享运行时（shared.py：SSE 通道/缓存/Web 状态）
│   │   └── web_fastapi/        # 新 Web 后端（FastAPI，8866 主入口）
│   └── utils/                  # 工具函数
├── web/                        # 新前端（Vue 3 + Vite，构建产物 dist/）
├── scripts/                    # 运维/调试脚本
│   ├── start_monitor.bat       # Windows 一键启动监控
│   ├── start_web.py            # 仅启动 Web 服务
│   ├── verify_ths_p0.py        # 同花顺 P0 数据源校验
│   └── archive/                # 历史调试/冒烟脚本（test_*）
├── logs/                       # 运行日志（finfeed.log）
├── pyproject.toml              # 构建配置（依赖唯一真相源）
├── requirements.txt            # 依赖便捷入口（与 pyproject 同步）
├── main.py                     # 主入口（转发至 finfeed.cli）
└── README.md
```

---

## 开发指南

### 添加新数据源

1. 在 `finfeed/core/parsers/` 下创建解析器类（继承 `BaseParser`）。
2. 在 `finfeed/config/sources.py` 中以 `NewsSource` 配置新数据源（名称、URL、解析器、调度档位等）。
3. 在 `finfeed/core/parsers/factory.py` 中注册解析器。

### 代码风格

项目统一采用以下规范（见 `pyproject.toml` 的 `[tool.black]` / `[tool.isort]`）：

```bash
black finfeed/        # 行宽 100，目标 Python 3.10
isort finfeed/        # profile = black
```

### 验证与调试

项目当前以内置开发/调试脚本做冒烟验证，位于 `scripts/archive/`（如 `test_parser.py`、`test_api.py`、`test_sentiment_*.py` 等）。正式 `pytest` 测试套件（`tests/`）为规划中项，后续迭代将把冒烟脚本迁移为标准测试。

---

## 贡献指南

欢迎通过 Issue 与 Pull Request 参与 FinFeed 的建设。

1. **提交问题（Issue）**：遇到缺陷或期望新功能，请先在 [GitHub Issues](https://github.com/finfeed/finfeed/issues) 检索是否已有相关记录，再新建 Issue 并附上复现步骤、日志片段与环境信息。
2. **分支策略**：从 `main` 切出特性分支（如 `feat/xxx`、`fix/xxx`），保持提交粒度清晰。
3. **开发环境**：按[安装步骤](#安装步骤)以可编辑模式安装，并在虚拟环境中开发。
4. **代码规范**：提交前执行 `black` 与 `isort`，确保通过静态检查；新增数据源/解析器请同步更新 `sources.py` 与工厂注册。
5. **文档同步**：功能、配置或 CLI 行为发生变更时，请同步更新 `README.md`。
6. **提交 PR**：描述改动动机、影响范围与验证方式；维护者会在 CI / 人工评审后合并。

---

## 许可证

本项目基于 **MIT License** 开源。详见仓库根目录的 [`LICENSE`](./LICENSE) 文件。

```
MIT License
Copyright (c) 2024 FinFeed Team
```

---
