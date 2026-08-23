# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏模块。

基于 easy-tdx（通达信 MAC 协议）实现：
- 沪深两市全市场个股/板块资金流向实时抓取
- 全市场资金流总览（净流入/净流出榜单）
- 板块轮动监控（资金状态分类、轮入/轮出切换信号、热力图与趋势）
- ECharts 可视化大屏 + FastAPI 实时刷新

快速启动：
    python -m finfeed.capital_dashboard
"""

from . import config
from .collector import (
    enrich_top_stocks,
    fetch_all_stocks,
    fetch_board_rankings,
    fetch_indices,
    fetch_stock_detail,
    fetch_unusual,
)
from .rotation import RotationReport, RotationSignal, analyze_rotation
from .anomaly import AnomalyDetector, AnomalyReport, detector
from .server import (
    app,
    create_router,
    start_refresh_worker,
    stop_refresh_worker,
    store,
)
from .snapshot import RefreshWorker, SnapshotStore

__version__ = "1.0.0"

__all__ = [
    "config",
    "app",
    "create_router",
    "start_refresh_worker",
    "stop_refresh_worker",
    "store",
    "RefreshWorker",
    "SnapshotStore",
    "RotationReport",
    "RotationSignal",
    "analyze_rotation",
    "AnomalyDetector",
    "AnomalyReport",
    "detector",
    "fetch_all_stocks",
    "fetch_board_rankings",
    "fetch_indices",
    "fetch_unusual",
    "fetch_stock_detail",
    "enrich_top_stocks",
    "__version__",
]
