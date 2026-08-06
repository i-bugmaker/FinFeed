#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量股票池与板块成分加载器（混合分层架构 P0 底座）

数据来源：东方财富 push2 行情列表接口（与现有 forum 解析器同源，HTTP 直连，
无需 MCP）。负责把 stock_meta 从 ~1565 扩充到全量 A 股，并构建板块↔成分股映射。

注意：第三方逐股情绪（方案E）由 tdx-connector MCP 在盘后快照层编排，
本模块只负责"标的基础面"与"板块成分"两类静态/半静态数据。
"""

import asyncio
import logging
from typing import Dict, List

import httpx

from finfeed.config.settings import API_CACHE_TTL
from finfeed.storage.database import db_upsert_stock_meta_full, get_db_manager

logger = logging.getLogger("news_monitor")

_EASTMONEY_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"

# 全 A 股筛选条件（沪市主板/科创板、深市主板/创业板、北交所）
_ALL_A_FS = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81"

_MARKET_MAP = {1: "沪市", 0: "深市", 2: "北交所"}


async def _get_json(url: str, params: Dict, timeout: float = 12.0) -> Dict:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def fetch_all_a_shares(page_size: int = 6000) -> List[Dict]:
    """拉取全量 A 股列表（代码/名称/行业/市场）

    Returns: [{code, name, industry, market}]
    """
    params = {
        "pn": 1,
        "pz": page_size,
        "fid": "f3",
        "fs": _ALL_A_FS,
        "fields": "f12,f13,f14,f100",
        "invt": 2,
        "fltt": 2,
    }
    data = await _get_json(_EASTMONEY_CLIST, params)
    diff = (data.get("data") or {}).get("diff") or []
    out = []
    for item in diff:
        code = (item.get("f12") or "").strip()
        if not code:
            continue
        market = _MARKET_MAP.get(item.get("f13"), "")
        out.append({
            "code": code,
            "name": (item.get("f14") or "").strip(),
            "industry": (item.get("f100") or "").strip(),
            "market": market,
        })
    return out


async def fetch_board_members(board_code: str, board_name: str = "",
                              sector_type: str = "concept", page_size: int = 1000) -> List[Dict]:
    """拉取某板块（概念/行业）的成分股。

    Args:
        board_code: 东财板块代码（如 BK0xxx / 概念板块）
        board_name: 板块名称（可选，用于写库）
        sector_type: 'concept' / 'sw_l1' / 'sw_l2'
    Returns: [{"code","name","weight"}]
    """
    params = {
        "pn": 1,
        "pz": page_size,
        "fid": "f3",
        "fs": f"b:{board_code}",
        "fields": "f12,f14",
        "invt": 2,
        "fltt": 2,
    }
    data = await _get_json(_EASTMONEY_CLIST, params)
    diff = (data.get("data") or {}).get("diff") or []
    return [{"code": (i.get("f12") or "").strip(), "name": (i.get("f14") or "").strip()} for i in diff]


async def populate_stock_meta() -> int:
    """全量刷新 stock_meta（code/name/industry/market）"""
    stocks = await fetch_all_a_shares()
    if not stocks:
        logger.warning("未获取到股票列表，跳过 stock_meta 刷新")
        return 0
    stock_map: Dict[str, Dict] = {}
    for s in stocks:
        stock_map[s["code"]] = {
            "name": s["name"],
            "industry": s["industry"],
            "market": s["market"],
        }
    n = db_upsert_stock_meta_full(stock_map)
    logger.info(f"stock_meta 刷新完成：写入/更新 {n} 只（来源全量 A 股）")
    return n


async def populate_board_members(board_code: str, board_name: str, sector_type: str) -> int:
    """刷新单个板块的成分股到 sector_members 表"""
    members = await fetch_board_members(board_code, board_name, sector_type)
    if not members:
        return 0
    from finfeed.storage.sentiment_store import upsert_sector_members_bulk
    rows = [(board_code, board_name, sector_type, m["code"], m["name"], 0.0) for m in members]
    n = upsert_sector_members_bulk(rows)
    logger.info(f"板块 {board_name}({board_code}) 成分股写入 {n} 条")
    return n


async def populate_sector_members_from_industry() -> int:
    """由 stock_meta.industry 派生板块→成分股映射（P0/P2 底座，无需额外板块API）。

    East Money clist 的 f100 即为个股行业（如"白酒""电池"），据此把每只股票归入
    其行业板块，写入 sector_members（sector_type='industry'）。聚合层
    aggregate_sector_from_stocks 即可据此由个股情绪算出板块情绪。
    依赖 populate_stock_meta() 已先刷新 stock_meta（含 industry）。
    """
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT code, name, industry FROM stock_meta WHERE industry IS NOT NULL AND industry != ''")
        rows = c.fetchall()
    if not rows:
        logger.warning("stock_meta.industry 为空，跳過行业板块映射（请先 run_populate_stock_meta）")
        return 0
    out = []
    for r in rows:
        ind = r["industry"].strip()
        out.append((f"IND:{ind}", ind, "industry", r["code"], r["name"], 0.0))
    n = upsert_sector_members_bulk_safe(out)
    logger.info(f"行业板块映射写入 {n} 条（来自 {len(rows)} 只股票）")
    return n


def upsert_sector_members_bulk_safe(rows) -> int:
    """包装 sentiment_store.upsert_sector_members_bulk（惰性导入避免循环依赖）"""
    from finfeed.storage.sentiment_store import upsert_sector_members_bulk
    return upsert_sector_members_bulk(rows)


def run_populate_stock_meta() -> int:
    """同步入口（CLI / 调度调用）：先刷新全量股票，再派生行业板块映射"""
    n1 = asyncio.run(populate_stock_meta())
    try:
        n2 = asyncio.run(populate_sector_members_from_industry())
    except Exception as e:  # 板块映射失败不阻塞主流程
        logger.warning(f"行业板块映射跳过: {e}")
        n2 = 0
    print(f"stock_meta 已刷新 {n1} 只；行业板块映射 {n2} 条")
    return n1 + n2


if __name__ == "__main__":
    # 单独运行：python -m finfeed.analysis.universe
    run_populate_stock_meta()
