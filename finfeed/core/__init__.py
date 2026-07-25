"""
核心业务逻辑模块
===============

提供新闻抓取、解析、去重、管道处理等核心功能。

子模块:
    - fetcher: 并发新闻抓取
    - pipeline: 数据处理管道
    - parsers: 多源解析器（策略模式）
    - monitor: 监控管理器
    - dedup: 去重服务
    - health: 健康检查
"""

from .fetcher import get_fetcher, fetch_all_news
from .pipeline import get_pipeline
from .monitor import MonitorManager
from .dedup import get_dedup_engine
from .health import HealthMonitor