#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘后 tdx 情绪快照（方案E）：把 tdx_ai_listening 的逐股多空事件分析写入 stock_sentiment

重要架构约束：tdx_ai_listening 是 MCP 工具，由 agent 在盘后快照层调用
（Python 监控进程调不到 MCP）。本模块提供可复用的三部分能力：
  1. get_universe_codes()         —— 全市场标的选取（方案E 目标池）
  2. tdx_weight_to_record()       —— 多空权重(0-100) → stock_sentiment 记录
  3. write_stock_sentiment_snapshot() / build_sector_snapshot() —— 写入与板块聚合
agent 编排流程：对目标池每只股票调用 tdx_ai_listening → 提取整体权重 →
tdx_weight_to_record → 批量 write_stock_sentiment_snapshot → build_sector_snapshot。
"""

import logging
from typing import Dict, List, Optional

from finfeed.storage import sentiment_store as ss
from finfeed.storage.database import get_db_manager
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("news_monitor")

SOURCE_NAME = "tdx_ai_listening"


def get_universe_codes() -> List[str]:
    """返回 stock_meta 全量代码（方案E 全市场逐股情绪快照目标池）"""
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT code FROM stock_meta")
        return [r["code"] for r in c.fetchall()]


def get_stock_name(code: str) -> str:
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT name FROM stock_meta WHERE code = ?", (code,))
        r = c.fetchone()
        return r["name"] if r else code


def tdx_weight_to_record(code: str, name: str, weight: float,
                         events_count: int = 1, trade_date: Optional[str] = None,
                         source: str = SOURCE_NAME) -> Dict:
    """tdx 多空权重(0-100) → stock_sentiment 记录

    weight>=50 偏多，<50 偏空；sentiment_score 线性映射到 [-1, 1]。
    """
    score = round((weight - 50) / 50.0, 4)
    if score > 0.2:
        label = "positive"
    elif score < -0.2:
        label = "negative"
    else:
        label = "neutral"
    return {
        "code": code,
        "name": name,
        "trade_date": trade_date or now_bj().strftime("%Y-%m-%d"),
        "sentiment_score": score,
        "sentiment_label": label,
        "heat": round(weight, 2),
        "mention_count": events_count,
        "pos_mentions": max(0, int(round(events_count * (weight / 100.0)))),
        "neg_mentions": max(0, int(round(events_count * (1 - weight / 100.0)))),
        "source": source,
    }


def write_stock_sentiment_snapshot(records: List[Dict]) -> int:
    """批量写入逐股情绪快照（幂等 upsert 到 stock_sentiment）"""
    if not records:
        return 0
    n = ss.upsert_stock_sentiment(records)
    logger.info(f"tdx 情绪快照写入 {n} 条")
    return n


def build_sector_snapshot(trade_date: Optional[str] = None, sector_type: Optional[str] = None) -> int:
    """由当日 stock_sentiment 聚合板块情绪指数（方案B 载体）"""
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    return ss.aggregate_sector_from_stocks(td, sector_type=sector_type)
