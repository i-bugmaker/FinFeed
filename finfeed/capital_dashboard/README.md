# 全市场资金流与板块轮动监控大屏

基于 **easy-tdx**（通达信 MAC 行情协议）的全市场资金流与板块轮动实时监控模块。
Python 后端轮询 TDX 行情服务器，前端以 ECharts 渲染大屏，支持定时/实时刷新。

> 说明：您需求中提到的包名为 `eazy-tdx`，PyPI 上对应的实际包为 **`easy-tdx`**（`pip install easy-tdx`），本模块即基于该包实现。

---

## 功能特性

### 1. 数据采集（easy-tdx 直连 TDX 行情服务器，不依赖通达信客户端）
- **全市场个股资金流**：一次性拉取沪深两市全部 A 股（约 5500+ 只，1~2 秒），涵盖
  主力净流入/流出、主力净比、5 分钟主力净额、3 日/5 日主力净额、成交额、换手率等实时字段；
- **个股资金流详情**：对榜单前 N 只股票逐股补全当日主力/散户流入流出与 5 日大单/中单净额；
- **板块资金流**：行业(HY)/概念(GN)板块排行——涨跌幅、成交额、主力净流入、上涨/下跌家数；
- **指数行情**：上证指数、深证成指、创业板指、科创50、沪深300 等主要指数；
- **市场异动**：封涨停/封跌停/逼近涨跌停等异动事件流。

### 2. 功能模块
- **全市场资金流总览**：按主力净流入/净流出双向排序的个股与板块榜单；
- **板块轮动监控**：
  - 板块资金状态五分类：`强势领涨 / 弱势领跌 / 价升背离 / 资金吸筹 / 中性`；
  - 资金轮入/轮出切换信号：板块主力净流入排名相对上一采样跳变超过阈值时触发；
  - 轮动热力图（板块 × 时间，主力净占比演变）与轮动趋势折线；
  - 领涨/领跌板块（涨跌 + 资金状态）联动展示；
- **实时刷新**：后端后台线程定时轮询（默认 8s），前端 5s 拉取，支持手动触发。

### 3. 大屏展示
- 深色科技风大屏，1920×1080 适配；排行表格、资金流条形图、轮动热力图、
  轮动趋势折线、轮动信号卡片、市场异动播报、底部跑马灯等组件齐全。

---

## 目录结构

```
finfeed/capital_dashboard/
├── __init__.py          # 包入口（组件导出）
├── __main__.py          # python -m finfeed.capital_dashboard 启动入口
├── config.py            # 全部可调参数（环境变量可覆盖）
├── tdx.py               # TDX 连接管理（单例、自动测速、断线重连）
├── collector.py         # 数据采集层（全市场资金流/板块/指数/异动/个股详情）
├── models.py            # 数据模型（纯 Python dataclass，直接 JSON 化）
├── rotation.py          # 板块轮动分析引擎（状态分类/信号/热力图/趋势）
├── snapshot.py          # 内存快照仓库 + 后台轮询线程
├── server.py            # FastAPI 服务（REST API + 大屏静态页）
├── web/
│   └── index.html       # ECharts 可视化大屏（单文件，无需构建）
└── README.md
```

---

## 快速开始

### 环境要求
- Python 3.10+
- 网络可访问通达信行情服务器（默认自动测速选择最快 MAC 服务器，端口 7709）

### 安装依赖

```bash
pip install easy-tdx fastapi uvicorn
# FinFeed 项目已有 fastapi/uvicorn，仅需补充 easy-tdx
```

### 启动服务

```bash
# 方式一：模块方式（推荐，独立端口 8090）
python -m finfeed.capital_dashboard

# 方式二：直接运行
python finfeed/capital_dashboard/server.py

# 方式三：uvicorn
uvicorn finfeed.capital_dashboard.server:app --host 0.0.0.0 --port 8090
```

浏览器访问 **http://localhost:8090** 查看大屏。

### 集成到 FinFeed 主应用（已默认启用）

本模块已挂载进 FinFeed 主 FastAPI 服务（`finfeed.ui.web_fastapi.app`，端口 8866）：

| 入口 | 说明 |
|---|---|
| `http://localhost:8866/capital` | 资金流大屏页面（自动注入 `/api/capital` 前缀） |
| `http://localhost:8866/api/capital/*` | 资金流 API（overview / ranking/stocks / ranking/boards / rotation / ranking/funds / health 等） |

主应用启动时自动拉起刷新线程，关闭时自动回收；若 easy-tdx 未安装，
主应用**优雅降级**（仅跳过该模块，不影响原有功能）。

依赖缺失时的重新启用：
```bash
pip install easy-tdx
# 重启主应用即可
```

### 配置（环境变量，全部可选）

| 变量 | 默认 | 说明 |
|---|---|---|
| `TDX_HOST` / `TDX_PORT` | 自动 / 7709 | 指定行情服务器；留空自动测速选最优 |
| `REFRESH_INTERVAL` | 8 | 主数据轮询周期（秒）；交易时段建议 5~15 |
| `DETAIL_REFRESH_EVERY` | 30 | 个股资金流详情补全周期（秒，逐股查询成本高） |
| `DETAIL_TOP_N` | 20 | 详情补全的榜单股票数量（净流入+净流出各 N） |
| `STOCK_TOP_N` | 15 | 个股榜单展示数量 |
| `BOARD_TOP_N` | 20 | 板块榜单展示数量 |
| `ROTATION_RANK_DELTA` | 4 | 轮动信号触发：主力净流入排名跳变位次阈值 |
| `HISTORY_LEN` | 120 | 轮动趋势/热力图保留的历史采样点数量 |
| `FUND_REFRESH_INTERVAL` | 20 | ETF/基金资金排行采集周期（秒，东财 push2 独立链路） |
| `FUND_TOP_N` | 12 | 基金排行每类别每方向的展示数量 |
| `DASH_HOST` / `DASH_PORT` | 0.0.0.0 / 8090 | Web 服务地址与端口 |

---

## REST API

| 接口 | 说明 |
|---|---|
| `GET /` | 大屏首页 |
| `GET /api/health` | 服务与数据刷新状态 |
| `POST /api/refresh` | 手动触发一轮数据刷新 |
| `GET /api/overview` | 市场总览：指数、涨跌家数、两市成交额、全市场主力净流入 |
| `GET /api/ranking/stocks?direction=in\|out&limit=15` | 个股资金流榜单（净流入/净流出） |
| `GET /api/ranking/boards?board_type=hy\|gn&sort=main_net\|change\|amount&limit=20` | 板块资金流榜单 |
| `GET /api/rotation` | 板块轮动分析：资金状态、切换信号、热力图、趋势序列 |
| `GET /api/unusual` | 市场异动事件流 |
| `GET /api/stock/{code}` | 单只个股资金流详情（实时查询） |

示例：

```bash
curl "http://localhost:8090/api/ranking/stocks?direction=in&limit=5"
curl "http://localhost:8090/api/rotation"
```

---

## 数据口径说明（重要）

通达信 MAC 行情协议的**资金流字段为两档口径**，与东方财富/同花顺的
「超大单/大单/中单/小单」四档不同：

| 维度 | 本模块数据来源 | 说明 |
|---|---|---|
| 主力净流入/净比/5分钟净额 | `get_stock_quotes_list` 批量报价 | **实时**，全市场 |
| 当日主力(≈超大单+大单)流入/流出 | `get_capital_flow`（0x1218） | 榜单 TOP N 个股补全 |
| 当日散户(≈中单+小单)流入/流出 | `get_capital_flow` | 同上 |
| 5 日大单/中单净额 | `get_capital_flow` | 协议提供的历史档位 |
| 3 日/5 日主力净额 | 批量报价 | 全市场实时 |

如需东财口径的当日四档（超大/大/中/小单）实时拆分，通达信协议无法直接提供，
可通过扩展 `collector.py` 增加数据源适配器（如东方财富 push2 接口）实现，
接口层 `models.py` 与前端均已预留字段。

---

## 架构与实时刷新机制

```
┌─────────────────────────────┐      ┌──────────────────────────┐
│  TDX 行情服务器 (7709)       │◄────►│ RefreshWorker 后台线程    │
└─────────────────────────────┘      │  · 每 REFRESH_INTERVAL 秒 │
                                     │  · 全市场个股/板块/指数/异动│
                                     │  · 低频补全个股详情        │
                                     └───────────┬──────────────┘
                                                 │ 写（加锁）
                                     ┌───────────▼──────────────┐
                                     │  SnapshotStore 内存快照    │
                                     │  · current 全量           │
                                     │  · history 轻量历史(趋势)  │
                                     │  · rotation 分析结果缓存   │
                                     └───────────┬──────────────┘
                                                 │ 读（加锁）
                                     ┌───────────▼──────────────┐
                                     │  FastAPI REST API         │
                                     │  ──────────────           │
                                     │  ECharts 大屏 (index.html)│
                                     │  · 5s 前端轮询            │
                                     └──────────────────────────┘
```

- **定时轮询**：后台 `RefreshWorker` 线程每 `REFRESH_INTERVAL` 秒采集一轮，
  一轮约 4~6 秒（全市场 1.8s + 板块 3.2s + 指数/异动 <0.1s）；
- **实时更新**：前端每 5 秒拉取各 API 渲染，图表增量更新；
- **容错**：单点采集失败不中断整轮；TDX 断线自动重连（含跨主机故障转移）；
  非交易时段显示最近一次收盘快照，行情恢复后自动继续。

---

## 二次开发指南

- **调整榜单口径**：改 `config.py` 的 `STOCK_TOP_N / BOARD_TOP_N`；
- **新增数据源**：在 `collector.py` 增加采集函数，在 `snapshot.py` 的
  `_collect_round` 中调用并写入快照，前端在 `web/index.html` 的 `loadAll()` 中消费；
- **调整轮动信号灵敏度**：`ROTATION_RANK_DELTA` 越小越灵敏；`ROTATION_FOCUS_N`
  控制热力图/趋势关注的板块数；
- **个股详情字段扩展**：`models.StockFlow` 已预留 `main_in/main_out/retail_in/retail_out/`
  `large_net_5d/mid_net_5d`，前端表格列按需增加。

---

## 常见问题

**Q: 页面显示"数据未就绪"？**
A: 首次采集需 5~10 秒（含服务器测速），稍等刷新即可；若持续失败查看
`logs/capital_dashboard.log` 中 `刷新轮次异常` 日志。

**Q: 非交易时段有数据吗？**
A: 有。显示最近一个交易日的收盘快照，轮动趋势/热力图记录服务运行期间的采样历史；
开盘后数据自动转为实时。

**Q: 如何降低 TDX 服务器压力？**
A: 调大 `REFRESH_INTERVAL`（如 15s）；`DETAIL_REFRESH_EVERY` 调大或 `DETAIL_TOP_N` 调小。

**Q: 与 FinFeed 主服务端口冲突？**
A: 通过 `DASH_PORT` 指定其他端口，或直接以独立进程部署。
