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

from .config.settings import DEFAULT_INTERVAL, DEFAULT_WEB_PORT
from .core.fetcher import fetch_all_news, get_fetcher
from .core.monitor import get_monitor
from .storage.database import db_get_recent_news, db_get_statistics, get_db, init_db
from .storage.exporter import export_to_csv, export_to_json
