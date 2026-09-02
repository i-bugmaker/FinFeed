#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘面复盘仪表盘快捷数据接口（同步 + 内存缓存）。

复用 easy-tdx 公开 API，为仪表盘「盘面复盘主控台」提供实时盘面数据：

- GET /api/easytdx/dashboard/overview  全市场涨跌统计（TdxClient.get_market_stat）
- GET /api/easytdx/dashboard/boards    板块涨幅榜 / 板块资金榜（MacClient.get_board_ranking）
- GET /api/easytdx/dashboard/stocks    个股涨幅 / 跌幅 / 成交额榜（MacClient.get_stock_quotes_list）
- GET /api/easytdx/dashboard/unusual   异动监控（MacClient.get_unusual）

要点：
- 同步返回（FastAPI 线程池执行 sync def，不阻塞事件循环）。
- 内存 TTL 缓存（默认 60s），避免仪表盘刷新 / 挂载时重复打通达信。
- easy-tdx 不可用时返回 ``{ok:false}``，前端优雅降级为空态卡片。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from easy_tdx.mac.enums import SortOrder, SortType
from fastapi import APIRouter, Query

logger = logging.getLogger("easytdx_dashboard")

router = APIRouter(prefix="/api/easytdx/dashboard", tags=["easytdx-dashboard"])

# 内存 TTL 缓存：key -> (expire_at, payload)
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_TTL = 60.0

# 板块类型：0 = 行业，1 = 概念（easy_tdx BoardType.HY / .GN）
_BOARD_TYPE = {"hy": 0, "gn": 1}
# 个股榜单映射：list -> (sort_type, sort_order)
_STOCK_LISTS = {
    "up": (SortType.CHANGE_PCT, SortOrder.DESC),
    "down": (SortType.CHANGE_PCT, SortOrder.ASC),
    "amount": (SortType.TOTAL_AMOUNT, SortOrder.DESC),
}

# 板块别名（沪/深/北）
_BOARD_ABBR = {"0": "深", "1": "沪", "2": "北"}


def _fetch(key: str, loader: Callable[[], Any], ttl: float = _TTL) -> dict:
    """带 TTL 缓存与异常兜底的同步取数。"""
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]
    try:
        data = loader()
    except Exception as e:  # noqa: BLE001
        logger.warning("dashboard[%s] failed: %s", key, e)
        return {"ok": False, "key": key, "error": str(e)[:200]}
    payload = {"ok": True, "key": key, "data": data, "ts": int(now)}
    with _CACHE_LOCK:
        _CACHE[key] = (now + ttl, payload)
    return payload


def _num(v, default=0):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# 全市场涨跌统计
@router.get("/overview")
def overview():
    def _load():
        from easy_tdx import TdxClient

        with TdxClient() as tc:
            df = tc.get_market_stat()
        if df is None or df.empty:
            raise ValueError("无全市场涨跌统计数据")
        r = df.iloc[0]
        up = int(_num(r.get("up_count")))
        down = int(_num(r.get("down_count")))
        neutral = int(_num(r.get("neutral_count")))
        total = int(_num(r.get("total_count")))
        # 涨跌停口径统一：优先用通达信 ZT/DT 池计数（可逐只下钻、与涨停聚焦一致）；
        # 若当天池未入库（盘中未采集），回退 880006 指数口径。
        limit_up = int(_num(r.get("limit_up_count")))
        limit_down = int(_num(r.get("limit_down_count")))
        try:
            from finfeed.market import store
            from finfeed.utils.time_utils import now_bj

            _td = now_bj().strftime("%Y-%m-%d")
            _up_pool = store.get_limit_pool(_td, "up")
            _down_pool = store.get_limit_pool(_td, "down")
            if _up_pool:
                limit_up = len(_up_pool)
            if _down_pool:
                limit_down = len(_down_pool)
        except Exception as e:  # noqa: BLE001
            logger.warning("通达信涨跌停池口径读取失败，回退指数口径: %s", e)
        return {
            "up": up,
            "down": down,
            "neutral": neutral,
            "suspended": int(_num(r.get("suspended_count"))),
            "total": total,
            "limit_up": limit_up,
            "limit_down": limit_down,
            "amount": _num(r.get("total_amount")),
            "volume": _num(r.get("total_volume")),
            "mcap": _num(r.get("total_market_cap")),
            "up_ratio": round(up / total * 100, 2) if total else 0,
        }

    return _fetch("overview", _load)


# 板块涨幅榜 / 板块资金榜
@router.get("/boards")
def boards(
    type_: str = Query("hy", alias="type", pattern="^(hy|gn)$"),
    sort: str = Query("change_pct", pattern="^(change_pct|main_net_amount)$"),
    top: int = Query(15, ge=1, le=30),
):
    board_type = _BOARD_TYPE[type_]

    def _load():
        from easy_tdx import MacClient

        with MacClient() as mc:
            df = mc.get_board_ranking(
                board_type=board_type,
                top_n=30,
                sort_by=sort,
                ascending=False,
            )
        if df is None or df.empty:
            raise ValueError("无板块排行数据")
        rows = []
        for _, r in df.head(top).iterrows():
            rows.append({
                "code": str(r.get("code") or ""),
                "name": str(r.get("name") or ""),
                "change_pct": _num(r.get("change_pct")),
                "amount": _num(r.get("amount")),
                "main_net_amount": _num(r.get("main_net_amount")),
                "up_count": int(_num(r.get("up_count"))),
                "down_count": int(_num(r.get("down_count"))),
                "member_count": int(_num(r.get("member_count"))),
            })
        return rows

    return _fetch(f"boards:{type_}:{sort}", _load)


# 个股涨幅 / 跌幅 / 成交额榜
@router.get("/stocks")
def stocks(
    list_: str = Query("up", alias="list", pattern="^(up|down|amount)$"),
    top: int = Query(15, ge=1, le=30),
):
    sort_type, sort_order = _STOCK_LISTS[list_]

    def _load():
        from easy_tdx import MacClient
        from easy_tdx.mac.enums import Category

        with MacClient() as mc:
            df = mc.get_stock_quotes_list(
                category=Category.A,
                start=0,
                count=top,
                sort_type=sort_type,
                sort_order=sort_order,
            )
        if df is None or df.empty:
            raise ValueError("无个股报价数据")
        rows = []
        for _, r in df.iterrows():
            pre = _num(r.get("pre_close"))
            close = _num(r.get("close"))
            chg = round((close - pre) / pre * 100, 2) if pre else None
            rows.append({
                "market": "" if r.get("market") is None else str(r.get("market")),
                "board": _BOARD_ABBR.get(str(r.get("market")), ""),
                "code": str(r.get("code") or ""),
                "name": str(r.get("name") or ""),
                "price": round(close, 2),
                "change_pct": chg,
                "amount": _num(r.get("amount")),
                "vol_ratio": _num(r.get("vol_ratio")),
                "turnover": _num(r.get("turnover")),
            })
        return rows

    return _fetch(f"stocks:{list_}", _load)


# 异动监控
@router.get("/unusual")
def unusual(count: int = Query(20, ge=1, le=50)):
    def _load():
        from easy_tdx import MacClient

        with MacClient() as mc:
            df = mc.get_unusual(market=2, start=0, count=count)
        if df is None or df.empty:
            raise ValueError("无异动数据")
        rows = []
        for _, r in df.head(count).iterrows():
            rows.append({
                "market": "" if r.get("market") is None else str(r.get("market")),
                "board": _BOARD_ABBR.get(str(r.get("market")), ""),
                "code": str(r.get("code") or ""),
                "name": str(r.get("name") or ""),
                "time": str(r.get("time") or ""),
                "desc": str(r.get("desc") or ""),
                "value": str(r.get("value") or ""),
            })
        return rows

    return _fetch("unusual", _load)
