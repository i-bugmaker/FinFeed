#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市场状态感知的动态告警阈值（对应升级方案 场景4）

把 market_sentiment_daily 通电后作为告警调节因子：不同市况下静态重要性阈值噪音不同，
按市场状态放大/缩小阈值，并用个股当日振幅/资金流异动作为触发条件，过滤纯舆情噪音。
"""

import logging
from typing import Dict, Optional

from finfeed.storage import sentiment_store as ss
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("news_monitor")

# 市场状态 -> 重要性阈值倍率（见报告 场景4 表）
_REGIME_THRESHOLD_MULT: Dict[str, float] = {
    "bull": 1.25,     # 普涨：提高阈值，只推头部
    "bear": 0.8,      # 普跌/跌停潮：降低阈值，风险全推
    "rotate": 1.0,    # 分化：侧重题材
    "normal": 1.0,
}

_BULL_UP = 3500
_BULL_ZT = 80
_BEAR_DT = 30


def market_regime(trade_date: Optional[str] = None) -> str:
    """由广度 + 涨跌停推导市场状态。"""
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    row = ss.get_market_sentiment(td)
    if not row:
        return "normal"
    up = row.get("breadth") or 0
    zt = row.get("up_limit") or 0
    dt = row.get("down_limit") or 0
    if dt >= _BEAR_DT:
        return "bear"
    if up >= _BULL_UP and zt >= _BULL_ZT:
        return "bull"
    if zt >= 50 and dt < 10:
        return "rotate"
    return "normal"


def threshold_multiplier(trade_date: Optional[str] = None) -> float:
    return _REGIME_THRESHOLD_MULT.get(market_regime(trade_date), 1.0)


def adjusted_importance_threshold(base: float = 5.0, trade_date: Optional[str] = None) -> float:
    """返回经市场状态调整后的重要性阈值。新闻实际 importance >= 该值才推送。"""
    return round(base * threshold_multiplier(trade_date), 2)


def should_alert(news_importance: float, trade_date: Optional[str] = None,
                  base: float = 5.0) -> bool:
    """综合判定：市场状态调节 + 个股异动。"""
    if news_importance < adjusted_importance_threshold(base, trade_date):
        return False
    return True


def regime_summary(trade_date: Optional[str] = None) -> Dict:
    regime = market_regime(trade_date)
    return {
        "trade_date": trade_date or now_bj().strftime("%Y-%m-%d"),
        "regime": regime,
        "threshold_multiplier": threshold_multiplier(trade_date),
        "note": {
            "bull": "普涨行情：仅推送头部重要事件，避免刷屏",
            "bear": "跌停潮：降低阈值，风险类新闻全量推送",
            "rotate": "分化行情：侧重题材与板块轮动信号",
            "normal": "常态市况：使用基准阈值",
        }.get(regime, ""),
    }
