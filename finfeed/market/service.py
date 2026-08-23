#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事实层对外编排服务

聚合各采集器，提供：
- init_market()             建表（启动时调用一次）
- run_universe()            股票池 + 在市标记 + 概念/行业板块
- run_daily_snapshot()      盘后快照：全市场资金流+宽度 / 涨跌停炸板池 / 龙虎榜 / 参考数据
- collect_bars_for_date()   指定交易日日线增量（仅在市标的）
- backfill_bars()           历史区间回补
- get_all_codes()           在市 A 股代码（批量采集唯一权威入口）
- diagnose()                链路自检：各端点组状态 + 各事实表行数

调度建议：
  盘前  run_universe()        —— 刷新名录与在市标记
  盘后  run_daily_snapshot()  —— 全部走 datacenter/push2ex，不依赖被限流的 push2
  错峰  collect_bars_for_date() —— push2his 增量，遇冷却自动中断，幂等可续
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from finfeed.storage.database import get_db_manager
from finfeed.utils.time_utils import now_bj

from . import (
    board,
    client,
    kline,
    quote,
    reference,
    snapshot,
    store,
    ths_hotrank,
    ths_limitup,
    universe,
)

logger = logging.getLogger("news_monitor")

_FACT_TABLES = [
    "stock_meta", "daily_bar", "sector_members", "limit_pool", "money_flow",
    "billboard", "margin_detail", "earnings_forecast", "ipo_calendar",
    "market_sentiment_daily", "news_stock_link",
]


def init_market() -> None:
    store.ensure_market_tables()
    logger.info("事实层数据表已就绪")


def get_all_codes(active_only: bool = True, board_name: Optional[str] = None) -> List[str]:
    """批量采集的股票代码来源。

    ⚠️ 默认只返回 is_active=1 的在市 A 股。历史上此函数返回全部 24759 条
       （含 15966 条新三板），直接导致日线采集把请求量放大数倍并触发 IP 限流。
    """
    if active_only:
        codes = store.get_active_codes(board_name)
        if codes:
            return codes
        logger.warning("in-market 标的为空，回退到全量 stock_meta（请先执行 run_universe）")
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT code FROM stock_meta ORDER BY code")
        return [r["code"] for r in c.fetchall()]


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------
async def run_universe(trade_date: Optional[str] = None) -> Dict[str, int]:
    return await universe.populate_all(trade_date)


async def run_daily_snapshot(trade_date: Optional[str] = None,
                             with_reference: bool = True) -> Dict[str, Any]:
    """盘后快照。各子任务互相隔离，单点失败不影响其余。"""
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    out: Dict[str, Any] = {"trade_date": td}

    try:
        out.update(await quote.collect_daily_market(td))
    except Exception as e:  # noqa: BLE001
        logger.error(f"行情快照失败: {e}")
        out["market_error"] = str(e)[:200]

    try:
        out["billboard"] = await board.collect_billboard(td)
    except Exception as e:  # noqa: BLE001
        logger.error(f"龙虎榜采集失败: {e}")
        out["billboard_error"] = str(e)[:200]

    if with_reference:
        try:
            out["reference"] = await reference.collect_all_reference(td)
        except Exception as e:  # noqa: BLE001
            logger.error(f"参考数据采集失败: {e}")
            out["reference_error"] = str(e)[:200]

    return out


async def collect_hotrank(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """同花顺热榜自动采集：落库为某交易日的多子榜快照。"""
    return await ths_hotrank.collect_all(trade_date)


async def collect_limitup_focus(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """同花顺涨停聚焦自动采集：涨停强度 / 连板天梯 / 最强风口 / 市场情绪 四模块落库。"""
    return await ths_limitup.collect_all(trade_date)


async def collect_bars_for_date(trade_date: Optional[str] = None,
                                limit: Optional[int] = None,
                                bars: int = kline.DEFAULT_LIMIT,
                                progress_cb=None) -> Dict[str, int]:
    """日线增量采集（仅在市标的，默认每只取最近 bars 根）。

    Args:
        progress_cb: 可选回调 progress_cb(done:int, total:int)，
                     沿 collect_daily_bars 透传到每 50 只一次。
    """
    codes = get_all_codes(active_only=True)
    if limit:
        codes = codes[:limit]
    return await kline.collect_daily_bars(
        codes, trade_date, limit=bars, progress_cb=progress_cb,
    )


async def backfill_bars(beg: str, end: Optional[str] = None,
                        limit: Optional[int] = None,
                        progress_cb=None) -> Dict[str, int]:
    """历史区间回补（区间模式，请务必错峰执行）。"""
    codes = get_all_codes(active_only=True)
    if limit:
        codes = codes[:limit]
    return await kline.collect_daily_bars(
        codes, end, beg=beg, progress_cb=progress_cb,
    )


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
def diagnose() -> Dict[str, Any]:
    """链路自检：端点组冷却状态 + 各事实表行数 + 最新交易日覆盖。"""
    db = get_db_manager()
    tables: Dict[str, Any] = {}
    with db.get_db() as c:
        for t in _FACT_TABLES:
            try:
                tables[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception as e:  # noqa: BLE001
                tables[t] = f"ERR: {str(e)[:60]}"
        try:
            row = c.execute(
                "SELECT COUNT(*) FROM stock_meta WHERE is_active = 1"
            ).fetchone()
            tables["stock_meta_active"] = row[0]
        except Exception:  # noqa: BLE001
            tables["stock_meta_active"] = "n/a"
    return {"endpoints": client.group_status(), "tables": tables}


# ----------------- 同步入口（CLI 调用） -----------------
def run_universe_sync(trade_date: Optional[str] = None) -> Dict[str, int]:
    return asyncio.run(run_universe(trade_date))


def run_daily_snapshot_sync(trade_date: Optional[str] = None,
                            with_reference: bool = True) -> Dict[str, Any]:
    return asyncio.run(run_daily_snapshot(trade_date, with_reference))


def collect_bars_sync(trade_date: Optional[str] = None,
                      limit: Optional[int] = None,
                      bars: int = kline.DEFAULT_LIMIT,
                      progress_cb=None) -> Dict[str, int]:
    return asyncio.run(
        collect_bars_for_date(trade_date, limit, bars, progress_cb=progress_cb),
    )


def collect_hotrank_sync(trade_date: Optional[str] = None) -> Dict[str, Any]:
    return asyncio.run(collect_hotrank(trade_date))


def collect_limitup_focus_sync(trade_date: Optional[str] = None) -> Dict[str, Any]:
    return asyncio.run(collect_limitup_focus(trade_date))


def backfill_bars_sync(beg: str, end: Optional[str] = None,
                       limit: Optional[int] = None,
                       progress_cb=None) -> Dict[str, int]:
    return asyncio.run(
        backfill_bars(beg, end, limit, progress_cb=progress_cb),
    )


def collect_snapshot_sync(trade_date: Optional[str] = None) -> Dict[str, Any]:
    return asyncio.run(snapshot.collect_market_snapshot(trade_date))


def collect_reference_sync(trade_date: Optional[str] = None) -> Dict[str, int]:
    return asyncio.run(reference.collect_all_reference(trade_date))
