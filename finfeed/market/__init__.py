#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""finfeed.market —— 东方财富结构化事实层

与新闻文本层（core/）平行，提供可校验的市场事实：
行情宽度、涨停/跌停/炸板池、资金流、龙虎榜、日线、两融、业绩预告、新股日历。
两层通过 stock_meta.code 关联，analysis/crossref.py 负责 join 与交叉分析。

模块分工：
    endpoints  端点常量 / 字段契约 / 报表名（唯一事实来源）
    client     HTTP 客户端：限速 + 组级冷却 + 熔断 + datacenter 分页器
    universe   股票池、在市标记、板块成分
    snapshot   全市场日频快照（资金流 + 市场宽度），datacenter 主链路
    quote      市场宽度、涨停/跌停/炸板池（push2ex）
    board      龙虎榜（datacenter）+ 单只资金流增强（push2，可降级）
    kline      日线增量 / 区间回补（push2his，可降级）
    reference  两融、业绩预告、新股日历（datacenter）
    store      建表与幂等写入
    service    对外编排与自检

对外入口（推荐从 service 调用）：
    from finfeed.market import service as market
    market.init_market()
    market.run_universe_sync()
    market.run_daily_snapshot_sync("2026-08-07")
    market.diagnose()
"""

from . import (
    board, client, endpoints, kline, quote, reference, service, snapshot,
    store, ths_hotrank, ths_limitup, universe,
)
from .client import RateLimited, datacenter_pages, group_status
from .store import (
    ensure_market_tables,
    get_active_codes,
    set_active_flags,
    purge_stock_meta,
    upsert_billboard,
    upsert_daily_bar,
    upsert_earnings_forecast,
    upsert_ipo_calendar,
    upsert_limit_pool,
    upsert_margin_detail,
    upsert_money_flow,
    upsert_news_stock_link,
    upsert_stock_meta_full,
    upsert_ths_hotrank,
    get_ths_hotrank,
    get_latest_ths_hotrank_date,
    get_ths_hotrank_dates,
    upsert_ths_limitup_pool,
    upsert_ths_limitup_ladder,
    upsert_ths_limitup_wind,
    upsert_ths_limitup_sentiment,
    get_ths_limitup_pool,
    get_ths_limitup_ladder,
    get_ths_limitup_wind,
    get_ths_limitup_sentiment,
    get_latest_ths_limitup_date,
    get_ths_limitup_dates,
)

__all__ = [
    "board", "client", "endpoints", "kline", "quote", "reference", "service",
    "snapshot", "store", "ths_hotrank", "ths_limitup", "universe",
    "RateLimited", "datacenter_pages", "group_status",
    "ensure_market_tables",
    "get_active_codes",
    "set_active_flags",
    "purge_stock_meta",
    "upsert_stock_meta_full",
    "upsert_daily_bar",
    "upsert_limit_pool",
    "upsert_money_flow",
    "upsert_billboard",
    "upsert_margin_detail",
    "upsert_earnings_forecast",
    "upsert_ipo_calendar",
    "upsert_news_stock_link",
    "upsert_ths_hotrank",
    "get_ths_hotrank",
    "get_latest_ths_hotrank_date",
    "get_ths_hotrank_dates",
    "upsert_ths_limitup_pool",
    "upsert_ths_limitup_ladder",
    "upsert_ths_limitup_wind",
    "upsert_ths_limitup_sentiment",
    "get_ths_limitup_pool",
    "get_ths_limitup_ladder",
    "get_ths_limitup_wind",
    "get_ths_limitup_sentiment",
    "get_latest_ths_limitup_date",
    "get_ths_limitup_dates",
]
