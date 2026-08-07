#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""龙虎榜采集 + 个股资金流增强

- 龙虎榜：datacenter RPT_DAILYBILLBOARD_DETAILSNEW（按交易日过滤，网关稳定无限流）。
- 全市场资金流：已迁移至 snapshot.py（一次报表拉全，见该模块头注释）。
  本模块仅保留 push2 **单只**资金流，用于对少量重点标的补齐中单/小单明细；
  push2 家族受 IP 限流保护，冷却期内自动降级返回 None，绝不阻塞主流程。

字段契约（龙虎榜，2026-08-07 实测）：
  SECURITY_CODE / SECURITY_NAME_ABBR / TRADE_DATE / EXPLANATION(上榜原因类别) /
  EXPLAIN(席位解读) / BILLBOARD_BUY_AMT / BILLBOARD_SELL_AMT / BILLBOARD_NET_AMT /
  BILLBOARD_DEAL_AMT / ACCUM_AMOUNT / TURNOVERRATE / CHANGE_RATE / CLOSE_PRICE /
  FREE_MARKET_CAP
"""

import asyncio
import logging
from typing import Dict, List, Optional

from .client import RateLimited, datacenter_pages, get_json
from .endpoints import (
    FLTT, FUND_FIELDS, PUSH2, RP_DAILYBILLBOARD, UT, dash_date, secid_of,
)
from . import store
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("news_monitor")

_BILLBOARD_COLUMNS = (
    "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLANATION,EXPLAIN,"
    "BILLBOARD_BUY_AMT,BILLBOARD_SELL_AMT,BILLBOARD_NET_AMT,BILLBOARD_DEAL_AMT,"
    "ACCUM_AMOUNT,TURNOVERRATE,CHANGE_RATE,CLOSE_PRICE,FREE_MARKET_CAP"
)


def _f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# 龙虎榜
# ---------------------------------------------------------------------------
async def fetch_billboard(trade_date: str) -> List[Dict]:
    """拉取某交易日龙虎榜明细（datacenter，分页全量）。"""
    raw = await datacenter_pages(
        RP_DAILYBILLBOARD,
        columns=_BILLBOARD_COLUMNS,
        filter_expr=f"(TRADE_DATE='{trade_date}')",
        sort_columns="TRADE_DATE",
        max_pages=20,
    )
    out: List[Dict] = []
    for r in raw:
        code = (r.get("SECURITY_CODE") or "").strip()
        if not code:
            continue
        out.append({
            "trade_date": dash_date(r.get("TRADE_DATE") or "") or trade_date,
            "code": code,
            "name": (r.get("SECURITY_NAME_ABBR") or "").strip(),
            # reason 用类别（可分组统计），detail 存席位解读
            "reason": (r.get("EXPLANATION") or "").strip(),
            "detail": (r.get("EXPLAIN") or "").strip(),
            "buy_amount": _f(r.get("BILLBOARD_BUY_AMT")),
            "sell_amount": _f(r.get("BILLBOARD_SELL_AMT")),
            "net_amount": _f(r.get("BILLBOARD_NET_AMT")),
            "deal_amount": _f(r.get("BILLBOARD_DEAL_AMT")),
            "accum_amount": _f(r.get("ACCUM_AMOUNT")),
            "turnover_ratio": _f(r.get("TURNOVERRATE")),
            "pct_chg": _f(r.get("CHANGE_RATE")),
            "close_price": _f(r.get("CLOSE_PRICE")),
            "free_mv": _f(r.get("FREE_MARKET_CAP")),
        })
    return out


async def collect_billboard(trade_date: Optional[str] = None) -> int:
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    rows = await fetch_billboard(td)
    if not rows:
        logger.info(f"[{td}] 龙虎榜无数据（非交易日或尚未发布）")
        return 0
    n = store.upsert_billboard(rows)
    logger.info(f"[{td}] 龙虎榜写入 {n} 条")
    return n


# ---------------------------------------------------------------------------
# 单只资金流增强（可选，push2，受限流保护）
# ---------------------------------------------------------------------------
async def fetch_money_flow(code: str) -> Optional[Dict]:
    """单只股票当日资金流明细（含中单/小单，全市场快照不提供）。

    push2 家族在本机可能处于限流冷却期，此时静默返回 None。

    ⚠️ 严禁用 push2delay 做本函数的降级源。2026-08-07 实测：延时集群在 push2
       断连时仍回 HTTP 200，但**资金流字段编号语义不同**——f62 恒为 1、
       f84 返回 194 亿（股本类数值而非小单净额）、f66/f72/f14 直接缺失。
       这种「200 + 错误语义」比失败更危险，会静默污染 money_flow 表。
       延时集群仅可用于纯行情字段（f43 收盘价 / f170 涨跌幅，已验证与
       datacenter 快照一致）。
    """
    try:
        data = await get_json(
            f"{PUSH2}/stock/get",
            params={"secid": secid_of(code), "fields": FUND_FIELDS,
                    "fltt": FLTT, "ut": UT},
            group="em_push2",
        )
    except RateLimited:
        return None
    except Exception as e:  # noqa: BLE001
        logger.debug(f"资金流 {code} 获取失败: {e}")
        return None

    d = data.get("data") or {}
    if not d:
        return None

    main_net = _f(d.get("f62"))
    super_net = _f(d.get("f66"))
    big_net = _f(d.get("f72"))
    # 语义护栏：主力净额 == 超大单净额 + 大单净额（push2 与 datacenter 均满足，
    # 已在 5191 只标的上验证 0 违反）。不成立即判定字段语义异常，拒绝入库。
    if main_net and abs(main_net - (super_net + big_net)) > max(1000.0, abs(main_net) * 0.05):
        logger.warning(f"资金流 {code} 主力净额恒等式不成立，疑似数据源异常，已丢弃")
        return None

    return {
        "code": code,
        "name": (d.get("f14") or "").strip(),
        "main_net": main_net,
        "super_net": super_net,
        "big_net": big_net,
        "mid_net": _f(d.get("f78")),
        "small_net": _f(d.get("f84")),
        "main_ratio": _f(d.get("f184")),
        "close_price": _f(d.get("f43")),
        "pct_chg": _f(d.get("f170")),
        "source": "push2",
    }


async def enrich_money_flow(codes: List[str], trade_date: Optional[str] = None) -> int:
    """对重点标的补齐中单/小单明细。冷却期内会提前退出，不做无谓施压。"""
    from .client import cooldown_remaining
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    rows: List[Dict] = []
    for code in codes:
        if cooldown_remaining("em_push2") > 0:
            logger.info(f"push2 冷却中，资金流增强提前结束（已完成 {len(rows)}/{len(codes)}）")
            break
        mf = await fetch_money_flow(code)
        if mf:
            mf["trade_date"] = td
            rows.append(mf)
    if not rows:
        return 0
    n = store.upsert_money_flow(rows)
    logger.info(f"[{td}] 资金流明细增强 {n} 只")
    return n


# 兼容旧调用名
collect_money_flow = enrich_money_flow


def run_collect_billboard(trade_date: Optional[str] = None) -> int:
    return asyncio.run(collect_billboard(trade_date))


def run_enrich_money_flow(codes: List[str], trade_date: Optional[str] = None) -> int:
    return asyncio.run(enrich_money_flow(codes, trade_date))
