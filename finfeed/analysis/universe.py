#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量股票池与板块成分加载器（兼容层）

历史说明：本模块曾直接使用 push2 clist/get 端点拉全量 A 股，而该端点已被东方财富限流
（报告唯一标红），导致 stock_meta 长期停留在 1,647 条、sector_members 为空、整条板块情绪
产品线静默失效。现数据源已迁移至事实层 finfeed.market.universe（datacenter 网关），
本文件仅保留对外兼容 API，逻辑全部委托 market 层。

用例：python -m finfeed.analysis.universe
"""

import asyncio
import logging
from typing import Dict, List

from finfeed.market.universe import (
    fetch_all_a_shares,
    fetch_all_board_members,
    populate_stock_meta,
    populate_concept_members,
    populate_industry_members,
    populate_all,
    run_populate_all,
)

logger = logging.getLogger("news_monitor")

# 兼容旧版 fetch_board_members 签名（单板块查询，委托全量映射后内存过滤）
_OLD_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"


async def fetch_board_members(board_code: str, board_name: str = "",
                              sector_type: str = "concept", page_size: int = 1000) -> List[Dict]:
    """兼容旧接口：返回某板块成分股（内存过滤全量映射）。"""
    all_rows = await fetch_all_board_members()
    out = []
    for sector_code, sector_name, st, code, name, _w in all_rows:
        if sector_code == board_code or sector_code == f"BK{board_code}":
            out.append({"code": code, "name": name})
    return out


async def populate_board_members(board_code: str, board_name: str, sector_type: str) -> int:
    """兼容旧接口：刷新单个板块成分股。"""
    members = await fetch_board_members(board_code, board_name, sector_type)
    if not members:
        return 0
    from finfeed.storage import sentiment_store as ss
    rows = [(board_code, board_name, sector_type, m["code"], m["name"], 0.0) for m in members]
    return ss.upsert_sector_members_bulk(rows)


async def populate_sector_members_from_industry() -> int:
    """兼容旧接口：由 stock_meta.industry 派生行业板块映射。"""
    return await populate_industry_members()


def run_populate_stock_meta() -> int:
    """同步入口（CLI / 调度调用）：刷新全量股票池 + 概念/行业板块映射。"""
    res = run_populate_all()
    total = sum(res.values())
    logger.info(f"stock_meta 已刷新 {res.get('stock_meta', 0)} 只；"
                f"概念板块 {res.get('concept', 0)} 条；行业板块 {res.get('industry', 0)} 条")
    return total


if __name__ == "__main__":
    run_populate_stock_meta()
