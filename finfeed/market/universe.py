#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""股票池与板块成分加载器（事实层 P0 底座）

数据源统一走东方财富 datacenter-web 网关（无限流），彻底绕开被拉黑的 clist/get。

三条主线：
  1. 全量 A 股名录   -> RPT_F10_BASIC_ORGINFO   -> stock_meta（含别名 alias）
  2. 在市标的判定     -> RPT_VALUEANALYSIS_DET   -> stock_meta.is_active
  3. 个股↔核心题材   -> RPT_F10_CORETHEME_BOARDTYPE -> sector_members(concept)

⚠️ 历史缺陷（本次修复）：
   RPT_F10_BASIC_ORGINFO 返回 24759 条，其中 15966 条是**新三板**、313 条老三板、
   115 条 B 股、8 条 CDR，真正的 A 股只有 8357 条。旧实现全量落库且 get_all_codes()
   直接返回全部代码，导致日线批量采集对 24759 个标的逐一请求 push2his ——
   请求量放大约 4 倍且绝大多数无效，是本机 IP 被东财限流封禁的直接诱因。
   现在：名录阶段按 SECURITY_TYPE 只保留 A 股；批量采集只用 is_active=1 的标的。
"""

import asyncio
import logging
from typing import Dict, List, Optional

from finfeed.storage import sentiment_store as ss

from . import store
from .client import datacenter_pages
from .endpoints import (
    BOARD_OF_TYPE,
    RP_F10_BASIC_ORGINFO,
    RP_F10_CORETHEME,
    RP_VALUATION,
    dash_date,
    is_a_share,
)

logger = logging.getLogger("news_monitor")

# A 股名录健康下限（实测全量 8357，含已退市历史标的）
MIN_STOCK_COUNT = 7000
# 在市标的健康下限（沪深约 5200 + 北交所约 700）
MIN_ACTIVE_COUNT = 4500


def _market_of(trade_market: str, sec_type: str) -> str:
    s = (trade_market or "") + " " + (sec_type or "")
    if "上海" in s or "上交" in s:
        return "沪市"
    if "北京" in s or "北交" in s:
        return "北交所"
    if "深圳" in s or "深交" in s:
        return "深市"
    return ""


# 1. 全量 A 股名录
async def fetch_all_a_shares() -> List[Dict]:
    """拉取全量证券名录并过滤出 A 股。

    Returns: [{code, name, industry, market, alias, list_date, security_type, board}]
    Raises: RuntimeError 条数不足（防止静默降级）
    """
    raw = await datacenter_pages(
        RP_F10_BASIC_ORGINFO,
        columns=("SECURITY_CODE,SECURITY_NAME_ABBR,SECURITY_TYPE,TRADE_MARKET,"
                 "EM2016,FORMERNAME,LISTING_DATE"),
        max_pages=20,
    )
    if not raw:
        raise RuntimeError("股票池网关返回空，已中止写库")

    rows: List[Dict] = []
    skipped = 0
    for r in raw:
        code = (r.get("SECURITY_CODE") or "").strip()
        sec_type = (r.get("SECURITY_TYPE") or "").strip()
        if not code:
            continue
        if not is_a_share(sec_type):
            skipped += 1
            continue
        name = (r.get("SECURITY_NAME_ABBR") or "").strip()
        former = r.get("FORMERNAME") or ""
        alias = [a.strip() for a in former.split("→") if a.strip() and a.strip() != name]
        rows.append({
            "code": code,
            "name": name,
            "industry": (r.get("EM2016") or "").strip(),
            "market": _market_of(r.get("TRADE_MARKET"), sec_type),
            "alias": alias,
            "list_date": dash_date(r.get("LISTING_DATE") or ""),
            "security_type": sec_type,
            "board": BOARD_OF_TYPE.get(sec_type, ""),
        })

    logger.info(f"证券名录 {len(raw)} 条 -> A 股 {len(rows)} 条（剔除新三板/B股/CDR {skipped} 条）")
    if len(rows) < MIN_STOCK_COUNT:
        raise RuntimeError(
            f"A 股名录仅 {len(rows)} 条 < 阈值 {MIN_STOCK_COUNT}，疑似网关异常，已中止写库"
        )
    return rows


# 2. 在市标的判定
async def _latest_valuation_date() -> str:
    """探测估值报表的最新交易日（1 次请求，pageSize=1）。

    报表默认按交易日倒序，首行即最新一期。
    """
    raw = await datacenter_pages(
        RP_VALUATION, columns="SECURITY_CODE,TRADE_DATE",
        page_size=1, max_pages=1, probe=True,
    )
    return dash_date(raw[0].get("TRADE_DATE") or "") if raw else ""


async def _fetch_valuation_by_date(trade_date: str) -> List[Dict]:
    """按交易日精确拉取估值报表（filter 生效后 count≈5500，2 页取完）。"""
    return await datacenter_pages(
        RP_VALUATION,
        columns="SECURITY_CODE,TRADE_DATE",
        filter_expr=f"(TRADE_DATE='{trade_date}')",
        max_pages=4,
    )


async def fetch_active_codes(trade_date: Optional[str] = None) -> List[str]:
    """取当日仍有行情的标的代码（判定「在市」）。

    主源 RPT_VALUEANALYSIS_DET 覆盖沪深全市场（含 B 股，需按 stock_meta 反查剔除），
    但**不含北交所**；北交所标的由 stock_meta.board='北交所' 直接补齐
    （北交所极少退市，误差可接受）。

    ⚠️ 该报表是**全历史**明细（count≈934 万），filter 缺失时会退化成
       「全历史前 N 行出现过的代码」——语义完全错误且结果不稳定。
       因此 trade_date 为空时必须先探测报表最新交易日，绝不允许无 filter 拉取。
    """
    td = trade_date or await _latest_valuation_date()
    if not td:
        logger.warning("估值报表最新交易日探测失败，中止在市判定（不做无 filter 全量拉取）")
        return []

    raw = await _fetch_valuation_by_date(td)
    if not raw and trade_date:
        # 指定交易日无数据（非交易日 / 数据未更新）时回退到报表最新一期
        fallback = await _latest_valuation_date()
        if fallback and fallback != td:
            logger.info(f"估值报表 {td} 无数据，回退到最新一期 {fallback}")
            raw = await _fetch_valuation_by_date(fallback)

    codes = {(x.get("SECURITY_CODE") or "").strip() for x in raw}
    codes.discard("")

    # 用 stock_meta 交集过滤掉 B 股，并补齐北交所
    from finfeed.storage.database import get_db_manager
    with get_db_manager().get_db() as c:
        c.execute("SELECT code, board FROM stock_meta")
        meta = {r["code"]: (r["board"] or "") for r in c.fetchall()}

    active = {x for x in codes if x in meta}
    bj = {k for k, v in meta.items() if v == "北交所"}
    active |= bj
    logger.info(f"在市判定：估值报表 {len(codes)} 只 ∩ A股名录 = {len(active) - len(bj - codes)}，"
                f"补北交所 {len(bj)} 只 -> 合计 {len(active)} 只")
    return sorted(active)


async def refresh_active_flags(trade_date: Optional[str] = None) -> Dict[str, int]:
    """刷新 stock_meta.is_active。批量采集前必须先跑一次。"""
    codes = await fetch_active_codes(trade_date)
    if len(codes) < MIN_ACTIVE_COUNT:
        logger.warning(
            f"在市标的仅 {len(codes)} 只 < 阈值 {MIN_ACTIVE_COUNT}，"
            f"疑似数据源异常，跳过 is_active 刷新以保留上次结果"
        )
        return {"active": -1, "inactive": -1}
    res = store.set_active_flags(codes)
    logger.info(f"在市标的刷新：活跃 {res['active']} / 非活跃 {res['inactive']}")
    return res


# 3. 板块成分
async def fetch_all_board_members() -> List[tuple]:
    """拉取全量「个股↔核心题材板块」映射。

    Returns: [(sector_code, sector_name, 'concept', code, name, weight)]
    """
    code2name: Dict[str, str] = {}
    try:
        from finfeed.storage.database import get_db_manager
        with get_db_manager().get_db() as c:
            c.execute("SELECT code, name FROM stock_meta")
            code2name = {r["code"]: r["name"] for r in c.fetchall()}
    except Exception:  # noqa: BLE001
        pass

    raw = await datacenter_pages(
        RP_F10_CORETHEME,
        columns="SECURITY_CODE,NEW_BOARD_CODE,BOARD_CODE,BOARD_NAME",
        max_pages=60,
    )
    rows: List[tuple] = []
    seen = set()
    for r in raw:
        code = (r.get("SECURITY_CODE") or "").strip()
        if not code or (code2name and code not in code2name):
            continue  # 只保留 A 股名录内的标的
        sector_code = (r.get("NEW_BOARD_CODE") or r.get("BOARD_CODE") or "").strip()
        sector_name = (r.get("BOARD_NAME") or "").strip()
        if not sector_code or not sector_name:
            continue
        key = (sector_code, code)
        if key in seen:
            continue
        seen.add(key)
        rows.append((sector_code, sector_name, "concept", code,
                     code2name.get(code, ""), 0.0))
    return rows


# 编排
async def populate_stock_meta() -> int:
    stocks = await fetch_all_a_shares()
    n = store.upsert_stock_meta_full(stocks)
    # 清理历史遗留的非 A 股记录（旧实现曾把 15966 条新三板一并落库）
    store.purge_stock_meta([s["code"] for s in stocks])
    logger.info(f"stock_meta 刷新完成：{n} 只 A 股")
    return n


async def populate_concept_members() -> int:
    rows = await fetch_all_board_members()
    if not rows:
        return 0
    n = ss.upsert_sector_members_bulk(rows)
    logger.info(f"核心题材板块成分写入 {n} 条")
    return n


async def populate_industry_members() -> int:
    """由 stock_meta.industry 派生行业板块映射（sector_type='industry'）。"""
    from finfeed.storage.database import get_db_manager
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT code, name, industry FROM stock_meta "
                  "WHERE industry IS NOT NULL AND industry != ''")
        src = c.fetchall()
    if not src:
        logger.warning("stock_meta.industry 为空，跳过行业板块映射")
        return 0
    rows = [(f"IND:{r['industry'].strip()}", r["industry"].strip(), "industry",
             r["code"], r["name"], 0.0) for r in src]
    n = ss.upsert_sector_members_bulk(rows)
    logger.info(f"行业板块映射写入 {n} 条（来自 {len(src)} 只股票）")
    return n


async def populate_all(trade_date: Optional[str] = None) -> Dict[str, int]:
    """一次性刷新：股票池 -> 在市标记 -> 概念板块 -> 行业板块。"""
    n_stock = await populate_stock_meta()
    act = await refresh_active_flags(trade_date)
    n_concept = await populate_concept_members()
    n_industry = await populate_industry_members()
    return {
        "stock_meta": n_stock,
        "active": act.get("active", 0),
        "concept": n_concept,
        "industry": n_industry,
    }


def run_populate_all(trade_date: Optional[str] = None) -> Dict[str, int]:
    return asyncio.run(populate_all(trade_date))
