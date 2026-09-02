#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参考事实数据（本次新增整合）

三个来源全部走 datacenter-web，无限流风险：

  融资融券个股明细  RPTA_WEB_RZRQ_GGMX   -> margin_detail
  业绩预告          RPT_PUBLIC_OP_PREDICT -> earnings_forecast
  新股申购日历      RPTA_APP_IPOAPPLY     -> ipo_calendar

⚠️ RPTA_WEB_RZRQ_GGMX 全历史 670 万行，**必须按 DATE 过滤**，否则会拖垮采集。
⚠️ 报表名坑：曾用的 `RPT_MAINFUNDINFLOW` / `RPT_IPO_XGSGLB` 均返回
   "报表配置不存在"，已分别替换为 `RPT_DMSK_TS_STOCKNEW`（见 snapshot.py）
   与 `RPTA_APP_IPOAPPLY`；`RPT_PUBLIC_OP_NEWPREDICT` 的正确名是
   `RPT_PUBLIC_OP_PREDICT`（少了 NEW）。
"""

import asyncio
import logging
from datetime import timedelta
from typing import Dict, List, Optional

from finfeed.utils.time_utils import now_bj

from . import store
from .client import datacenter_pages
from .endpoints import RP_IPO_APPLY, RP_OP_PREDICT, RP_RZRQ_DETAIL, dash_date

logger = logging.getLogger("news_monitor")

_RZRQ_COLUMNS = ("DATE,SCODE,SECNAME,MARKET,RZYE,RZMRE,RZJME,RQYE,RQYL,"
                 "RZRQYE,RZYEZB,ZDF")
_PREDICT_COLUMNS = ("SECURITY_CODE,SECURITY_NAME_ABBR,NOTICE_DATE,REPORTDATE,"
                    "FORECASTTYPE,FORECASTCONTENT,FORECASTL,FORECASTT,"
                    "INCREASEL,INCREASET,CHANGEREASONDSCRPT,ISLATEST")
_IPO_COLUMNS = ("SECURITY_CODE,APPLY_CODE,SECURITY_NAME_ABBR,APPLY_DATE,LISTING_DATE,"
                "BALLOT_NUM_DATE,ONLINE_PAY_DATE,ISSUE_PRICE,ONLINE_APPLY_UPPER,"
                "TRADE_MARKET,INDUSTRY_NAME,AFTER_ISSUE_PE,ONLINE_ISSUE_LWR")


def _f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


# 东财布尔字段的真值集合。
# ⚠️ 历史缺陷：RPT_PUBLIC_OP_PREDICT 的 ISLATEST 实际返回 **'T'**（非 '1'），
#    旧白名单只认 ("1","True","true")，导致 1235 条业绩预告全部落库为
#    is_latest=0，任何按「最新一期」筛选的查询都返回空集。
_TRUE_TOKENS = {"1", "T", "Y", "TRUE", "YES"}


def _truthy(v, default: int = 1) -> int:
    """东财布尔字段归一化为 0/1。空值按 default 处理。"""
    if v is None or v == "":
        return default
    return 1 if str(v).strip().upper() in _TRUE_TOKENS else 0


# 融资融券
async def fetch_margin_detail(trade_date: str) -> List[Dict]:
    """某交易日两融个股明细。两融数据 T+1 发布，当日盘后通常取不到。"""
    raw = await datacenter_pages(
        RP_RZRQ_DETAIL,
        columns=_RZRQ_COLUMNS,
        filter_expr=f"(DATE='{trade_date}')",
        sort_columns="RZJME",
        # 不指定 page_size：由 endpoints.RP_PAGE_SIZE 提供实测上限（500）。
        # 曾硬编码 5000，被服务端静默截断为 500 且旧分页器误判末页，只取到 500/4422。
        max_pages=15,
    )
    out: List[Dict] = []
    for r in raw:
        code = (r.get("SCODE") or "").strip()
        if not code:
            continue
        out.append({
            "trade_date": dash_date(r.get("DATE") or "") or trade_date,
            "code": code,
            "name": (r.get("SECNAME") or "").strip(),
            "market": (r.get("MARKET") or "").strip(),
            "fin_balance": _f(r.get("RZYE")),
            "fin_buy": _f(r.get("RZMRE")),
            "fin_net": _f(r.get("RZJME")),
            "short_balance": _f(r.get("RQYE")),
            "short_volume": _f(r.get("RQYL")),
            "total_balance": _f(r.get("RZRQYE")),
            "balance_ratio": _f(r.get("RZYEZB")),
            "pct_chg": _f(r.get("ZDF")),
        })
    return out


async def collect_margin_detail(trade_date: Optional[str] = None,
                                lookback: int = 3) -> int:
    """采集两融明细。两融 T+1 发布，向前回溯若干日直到取到数据。"""
    base = now_bj()
    if trade_date:
        from datetime import datetime
        base = datetime.strptime(trade_date, "%Y-%m-%d")
    for i in range(lookback + 1):
        d = (base - timedelta(days=i)).strftime("%Y-%m-%d")
        rows = await fetch_margin_detail(d)
        if rows:
            n = store.upsert_margin_detail(rows)
            logger.info(f"[{d}] 两融明细写入 {n} 条")
            return n
    logger.info(f"两融明细：回溯 {lookback} 日均无数据（T+1 发布，属正常）")
    return 0


# 业绩预告
async def fetch_earnings_forecast(since: str) -> List[Dict]:
    """自 since（含）以来公告的业绩预告。"""
    raw = await datacenter_pages(
        RP_OP_PREDICT,
        columns=_PREDICT_COLUMNS,
        filter_expr=f"(NOTICE_DATE>='{since}')",
        sort_columns="NOTICE_DATE",
        max_pages=20,
    )
    out: List[Dict] = []
    for r in raw:
        code = (r.get("SECURITY_CODE") or "").strip()
        if not code:
            continue
        out.append({
            "code": code,
            "name": (r.get("SECURITY_NAME_ABBR") or "").strip(),
            "report_date": dash_date(r.get("REPORTDATE") or ""),
            "notice_date": dash_date(r.get("NOTICE_DATE") or ""),
            "forecast_type": (r.get("FORECASTTYPE") or "").strip(),
            "forecast_content": (r.get("FORECASTCONTENT") or "").strip(),
            "profit_low": _f(r.get("FORECASTL")),
            "profit_high": _f(r.get("FORECASTT")),
            "increase_low": _f(r.get("INCREASEL")),
            "increase_high": _f(r.get("INCREASET")),
            "change_reason": (r.get("CHANGEREASONDSCRPT") or "").strip()[:1000],
            "is_latest": _truthy(r.get("ISLATEST")),
        })
    return out


async def collect_earnings_forecast(days: int = 30) -> int:
    since = (now_bj() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = await fetch_earnings_forecast(since)
    if not rows:
        logger.info(f"业绩预告：{since} 以来无数据")
        return 0
    n = store.upsert_earnings_forecast(rows)
    logger.info(f"业绩预告写入 {n} 条（{since} 起）")
    return n


# 新股申购日历
async def fetch_ipo_calendar(since: str) -> List[Dict]:
    raw = await datacenter_pages(
        RP_IPO_APPLY,
        columns=_IPO_COLUMNS,
        filter_expr=f"(APPLY_DATE>='{since}')",
        sort_columns="APPLY_DATE",
        sort_types=1,
        max_pages=10,
    )
    out: List[Dict] = []
    for r in raw:
        code = (r.get("SECURITY_CODE") or "").strip()
        if not code:
            continue
        out.append({
            "code": code,
            "apply_code": (r.get("APPLY_CODE") or "").strip(),
            "name": (r.get("SECURITY_NAME_ABBR") or "").strip(),
            "apply_date": dash_date(r.get("APPLY_DATE") or ""),
            "listing_date": dash_date(r.get("LISTING_DATE") or ""),
            "ballot_date": dash_date(r.get("BALLOT_NUM_DATE") or ""),
            "pay_date": dash_date(r.get("ONLINE_PAY_DATE") or ""),
            "issue_price": _f(r.get("ISSUE_PRICE")),
            "apply_upper": _f(r.get("ONLINE_APPLY_UPPER")),
            "market": (r.get("TRADE_MARKET") or "").strip(),
            "industry": (r.get("INDUSTRY_NAME") or "").strip(),
            "issue_pe": _f(r.get("AFTER_ISSUE_PE")),
            "ballot_rate": _f(r.get("ONLINE_ISSUE_LWR")),
        })
    return out


async def collect_ipo_calendar(back_days: int = 30) -> int:
    since = (now_bj() - timedelta(days=back_days)).strftime("%Y-%m-%d")
    rows = await fetch_ipo_calendar(since)
    if not rows:
        logger.info(f"新股日历：{since} 以来无数据")
        return 0
    n = store.upsert_ipo_calendar(rows)
    logger.info(f"新股日历写入 {n} 条（{since} 起）")
    return n


# 编排
async def collect_all_reference(trade_date: Optional[str] = None) -> Dict[str, int]:
    return {
        "margin": await collect_margin_detail(trade_date),
        "forecast": await collect_earnings_forecast(),
        "ipo": await collect_ipo_calendar(),
    }


def run_collect_all_reference(trade_date: Optional[str] = None) -> Dict[str, int]:
    return asyncio.run(collect_all_reference(trade_date))
