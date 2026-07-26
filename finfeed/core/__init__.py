"""
核心业务逻辑模块
===============

提供新闻抓取、解析、管道处理等核心功能。

子模块:
    - fetcher: 并发新闻抓取
    - pipeline: 数据处理管道
    - parsers: 多源解析器（策略模式）
    - monitor: 监控管理器
    - health: 健康检查
"""

from .fetcher import get_fetcher, fetch_all_news
from .pipeline import process_and_store, process_news_items
from .monitor import get_monitor, NewsMonitor
from .health import HealthMonitor, get_health_monitor
