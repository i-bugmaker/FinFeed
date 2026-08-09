# FinFeed - 实时金融新闻监控系统

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Version](https://img.shields.io/badge/version-2.1.0-orange.svg)

模块化架构的新闻抓取、分析、推送系统，支持多源实时监控。

## 功能特性

- **多源抓取**: 支持新浪财经、财联社、金十数据、巨潮资讯等20+新闻源
- **实时监控**: 定时抓取，秒级更新
- **智能分析**: 情感分析、重要性评估、关键词提取
- **去重机制**: 基于内容指纹的智能去重（L1 URL / L2 标题哈希 / L3 SimHash / L4 时间+关键词）
- **Web 界面**: 实时仪表盘、历史查询、情感趋势、财经日历、市场数据、AI 分析
- **数据导出**: 支持 JSON/CSV/Excel/Markdown 格式

> 数据源完整性提示：本项目依赖公开网页/接口抓取。数据源结构与反爬策略会变化，
> 若某数据源持续失败请查看运行日志（logs/finfeed.log）中的健康监控信息。

## 技术架构

```
┌─────────────────────────────────────────────────────────┐
│                     UI Layer                            │
│  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │   Web Dashboard │  │        Terminal Output      │  │
│  └────────┬────────┘  └─────────────────────────────┘  │
└───────────┼────────────────────────────────────────────┘
            │
┌───────────▼────────────────────────────────────────────┐
│                    Core Layer                           │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────────┐  │
│  │ Monitor │→ │  Fetcher │→ │ Parser  │→ │ Pipeline │  │
│  │ Manager │  │(并发抓取) │  │(策略模式)│  │(处理管道)│  │
│  └─────────┘  └──────────┘  └─────────┘  └─────┬──────┘  │
│                                                 │        │
│                                   ┌─────────────▼───────┐│
│                                   │    Dedup Service    ││
│                                   └─────────────────────┘│
└───────────────────────────────────────┬─────────────────┘
                                        │
┌───────────────────────────────────────▼─────────────────┐
│                  Storage Layer                          │
│  ┌─────────────────────────┐  ┌───────────────────────┐ │
│  │     SQLite Database     │  │       Exporter        │ │
│  │                         │  │ (JSON/CSV/Excel/MD)   │ │
│  └─────────────────────────┘  └───────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## 快速开始

### 安装依赖

```bash
# 推荐：可编辑安装（与 pyproject.toml 依赖清单一致）
pip install -e .

# 或仅安装依赖（内容与 pyproject.toml 同步）
pip install -r requirements.txt

# 浏览器渲染依赖（用于绕过部分数据源反爬虫）
playwright install chromium
```

### 启动监控

```bash
# 启动实时监控（默认 Web 后端 = FastAPI 双轨并行）
python main.py

# 自定义抓取间隔（每60秒）
python main.py --interval 60

# 只抓取一次
python main.py --once

# 显式指定 Web 后端模式
python main.py --web fastapi   # 默认：FastAPI(8866) + 旧 server.py 回退(8867)
python main.py --web legacy    # 仅旧版 server.py 单轨（监听 --port，默认 8866）
```

#### Web 界面（方案 D：双轨并行）

自 v2.1 起，Web 前端为 Vue 3 + Vite 构建的 SPA，由 FastAPI 同源托管；
旧版 `server.py`（服务端模板渲染）保留为回退通道，二者并行运行。

| 端口 | 服务 | 说明 |
|------|------|------|
| `8866` | FastAPI + Vue SPA（新） | 默认主入口，现代 SaaS 亮色风格 |
| `8867` | 旧 `server.py`（回退） | 与旧接口完全一致，仅 UI 为旧版模板 |

- **API 交互文档（Swagger UI）**：`http://127.0.0.1:8866/docs`（OpenAPI 在 `/openapi.json`）
- **交互式文档（ReDoc）**：`http://127.0.0.1:8866/redoc`
- **健康检查**：`http://127.0.0.1:8866/api/ping`
- 约定沿用旧版：**红涨绿跌**（涨=红 `#e5484d`，跌=绿 `#16a34a`）。

> **无浏览器 / 仅预览界面**：若运行环境没有可用浏览器（Playwright 无法启动，监控器会崩溃），
> 可用 `--web-only` 仅启动 Web 服务，避开监控器，稳定预览新界面与已有数据：
> ```bash
> python main.py --web-only          # 仅 Web（8866 新 / 8867 回退），Ctrl+C 停止
> ```

前端为构建产物，需 Node ≥ 18。开发/重新构建：

```bash
cd web
npm install        # 安装依赖（vue / vue-router / pinia / axios / echarts / vite）
npm run dev        # 开发服务器（代理 /api → 8866，支持热更新）
npm run build      # 产出 web/dist，由 FastAPI 静态托管
```

> 注：`web/dist` 已被 FastAPI 静态挂载为 SPA 入口；若 `web/dist` 不存在，
> FastAPI 仅提供 API（不含前端页面），此时可访问 8867 回退界面。

#### 回退到旧版 Web（回滚）

若新后端异常，可一键切回旧版：

```bash
python main.py --web legacy           # 仅旧版 server.py 单轨
# 或直接以前端开发服务器 + 旧后端联调：
cd web && npm run dev                  # 浏览器访问 http://127.0.0.1:5173
```

旧版 `finfeed/ui/web` 的全量副本已备份于 `backup_web_20260809/`，
如需完整还原旧版前端，将该目录内容覆盖回 `finfeed/ui/web/` 即可。

### 数据导出

```bash
# 导出为 JSON
python main.py --export json

# 导出为 CSV
python main.py --export csv

# 按日期范围导出
python main.py --export json --start 2024-01-01 --end 2024-01-31
```

## 项目结构

```
FinFeed/
├── finfeed/                    # 主包
│   ├── alerts/                 # 告警与订阅
│   ├── analysis/               # 文本分析（情感/重要性/关键词）
│   ├── config/                 # 配置管理
│   ├── core/                   # 核心业务
│   │   └── parsers/            # 解析器（策略模式）
│   ├── ecal/                   # 财经日历（东方财富四大日历）
│   ├── llm/                    # 大模型分析
│   ├── market/                 # 市场行情数据
│   ├── storage/                # 数据持久化
│   ├── ui/                     # 用户界面
│   │   ├── web/                # 旧版 Web（server.py + 模板，8867 回退）
│   │   └── web_fastapi/        # 新 Web 后端（FastAPI，8866 主入口）
│   └── utils/                  # 工具函数
├── web/                        # 新前端（Vue 3 + Vite，构建产物 dist/）
├── tests/                      # 测试目录（pytest）
├── scripts/                    # 运维/调试脚本
├── backup_web_20260809/        # 旧版前端全量备份（回滚用）
├── pyproject.toml              # 构建配置（依赖唯一真相源）
├── main.py                     # 主入口
```

## 配置说明

配置文件位于 `finfeed/config/settings.py`:

- `DEFAULT_INTERVAL`: 默认抓取间隔（秒）
- `DEFAULT_WEB_PORT`: 默认 Web 端口
- `LOG_PATH`: 日志文件路径
- `MAX_NEWS_KEEP_DAYS`: 新闻保留天数

数据源配置位于 `finfeed/config/sources.py`，支持动态添加新源。

## 开发指南

### 添加新数据源

1. 创建解析器类（继承 `BaseParser`）
2. 在 `finfeed/config/sources.py` 中配置数据源
3. 在 `finfeed/core/parsers/factory.py` 中注册解析器

### 代码规范

```bash
# 代码格式化
black finfeed/

# 导入排序
isort finfeed/

# 运行测试
pytest tests/
```

## 许可证

MIT License
