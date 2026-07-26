"""
FinFeed - 实时金融新闻监控系统
=============================

模块化架构的新闻抓取、分析、推送系统。

主要模块:
    - analysis: 文本分析（情感、重要性）
    - config: 配置管理
    - core: 核心业务逻辑（抓取、解析、管道）
    - storage: 数据持久化
    - ui: 用户界面（Web、终端）
    - utils: 工具函数
"""

__version__ = "2.0.0"

from .core.monitor import get_monitor
from .core.fetcher import get_fetcher, fetch_all_news
from .storage.database import init_db, db_get_recent_news, db_get_statistics, get_db
from .storage.exporter import export_to_json, export_to_csv
from .ui.web.server import start_web_server, stop_web_server
from .config.settings import DEFAULT_WEB_PORT, DEFAULT_INTERVAL
