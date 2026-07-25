# FinFeed - 实时金融新闻监控系统

![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

模块化架构的新闻抓取、分析、推送系统，支持多源实时监控。

## 功能特性

- **多源抓取**: 支持新浪财经、财联社、金十数据、巨潮资讯等20+新闻源
- **实时监控**: 定时抓取，秒级更新
- **智能分析**: 情感分析、重要性评估、关键词提取
- **去重机制**: 基于内容指纹的智能去重
- **Web 界面**: 实时仪表盘、历史查询、情感趋势
- **数据导出**: 支持 JSON/CSV/Excel/Markdown 格式

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
pip install -r requirements.txt
```

### 启动监控

```bash
# 启动实时监控
python main.py

# 自定义抓取间隔（每60秒）
python main.py --interval 60

# 只抓取一次
python main.py --once

# 启动 Web 服务（默认端口8080）
python main.py --port 8080
```

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
│   ├── analysis/               # 文本分析
│   ├── config/                 # 配置管理
│   ├── core/                   # 核心业务
│   │   └── parsers/            # 解析器（策略模式）
│   ├── storage/                # 数据持久化
│   ├── ui/                     # 用户界面
│   │   └── web/templates/      # HTML 模板
│   └── utils/                  # 工具函数
├── tests/                      # 测试目录
├── scripts/                    # 启动脚本
├── pyproject.toml              # 构建配置
├── requirements.txt            # 依赖列表
└── main.py                     # 主入口
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
