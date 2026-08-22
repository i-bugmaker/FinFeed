#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FinFeed 选股评分模块。

基于 easy-tdx 实时行情与基本面数据，通过五维加权打分（资金面 / 动量趋势 /
估值 / 量价活跃 / 质量稳定）实现系统化量化选股。

快速使用：
    from finfeed.screener import load_config, scoring, datasource
    cfg = load_config()
    df = datasource.fetch_universe()
    scores = scoring.score_frame(df, cfg, technical_enabled=True)
"""

from __future__ import annotations

from .config import DEFAULT_CONFIG, ScreenerConfig, load_config
from .datasource import (
    close,
    enrich_technical,
    fetch_universe,
    load_snapshot_csv,
    save_snapshot_csv,
)
from .models import RawStock, ScreenerResult, StockScore
from .scoring import build_factor_row, is_eligible, score_frame, score_one

__all__ = [
    "DEFAULT_CONFIG",
    "ScreenerConfig",
    "load_config",
    "close",
    "enrich_technical",
    "fetch_universe",
    "load_snapshot_csv",
    "save_snapshot_csv",
    "RawStock",
    "ScreenerResult",
    "StockScore",
    "build_factor_row",
    "is_eligible",
    "score_frame",
    "score_one",
]

__version__ = "1.0.0"
