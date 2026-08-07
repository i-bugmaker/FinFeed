#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全市场日频快照（资金流 + 涨跌分布）

单一数据源：datacenter `RPT_DMSK_TS_STOCKNEW`
  实测 2026-08-07：count=5191，覆盖沪深全部在市 A 股（不含北交所），
  **服务端 pageSize 硬上限 500**，需 11 页拉全。

一次快照同时供给两个下游：
  1. money_flow 表（主力/超大单/大单净额 + 收盘价/涨跌幅/换手/机构参与度）
  2. 市场宽度（涨/跌/平家数、涨跌停估算）—— 替代语义错误且被限流的 push2 ulist 路径

⚠️ 本模块存在的意义：旧实现用 push2 `stock/get` 对 5000 只股票**逐只**请求资金流，
   即便按 2 req/s 也需 45 分钟连续施压，必然触发东财按 IP 的滑动窗口限流，
   结果 money_flow 表长期为 0 行。改用本报表后：11 次请求、约 4 秒完成。

字段契约（实测）：
  SECURITY_CODE / SECURITY_NAME_ABBR / TRADE_DATE / CLOSE_PRICE / CHANGE_RATE /
  TURNOVERRATE / PRIME_INFLOW(主力净额) / SUPERDEAL_INFLOW / SUPERDEAL_OUTFLOW /
  BIGDEAL_INFLOW / BIGDEAL_OUTFLOW / RATIO(主力净占比) / ORG_PARTICIPATE(机构参与度)

  恒等式已验证：PRIME_INFLOW == (SUPERDEAL_IN - SUPERDEAL_OUT) + (BIGDEAL_IN - BIGDEAL_OUT)
  该报表不提供中单/小单，mid_net / small_net 置 0（如需可用 push2 单只增强）。
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple

from .client import datacenter_pages
from .endpoints import RP_MAINFUND, dash_date
from . import store
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("news_monitor")

# 快照健康下限：低于此值判定为数据源异常，不写库
MIN_SNAPSHOT_ROWS = 3000

_SNAPSHOT_COLUMNS = (
    "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,CLOSE_PRICE,CHANGE_RATE,"
    "TURNOVERRATE,PRIME_INFLOW,SUPERDEAL_INFLOW,SUPERDEAL_OUTFLOW,"
    "BIGDEAL_INFLOW,BIGDEAL_OUTFLOW,RATIO,ORG_PARTICIPATE"
)


def _f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


async def fetch_market_snapshot(trade_date: Optional[str] = None) -> Tuple[List[Dict], str]:
    """拉取全市场资金流 + 行情快照。

    Args:
        trade_date: 'YYYY-MM-DD'。报表只保留最新一个交易日，传入历史日期时
                    若无匹配数据会回退到报表自带日期（并在返回值中告知真实日期）。
    Returns:
        (rows, snapshot_date)，rows 已规整为项目内部字段名。
    """
    raw = await datacenter_pages(
        # page_size 由 endpoints.RP_PAGE_SIZE 统一提供（实测上限 500）
        RP_MAINFUND, columns=_SNAPSHOT_COLUMNS, max_pages=30,
    )
    if not raw:
        logger.warning("全市场快照返回空（datacenter 异常）")
        return [], ""

    snapshot_date = dash_date(raw[0].get("TRADE_DATE") or "")
    if trade_date and snapshot_date and snapshot_date != trade_date:
        logger.info(f"快照报表实际日期 {snapshot_date}，与请求日期 {trade_date} 不一致（报表仅存最新一期）")

    rows: List[Dict] = []
    for r in raw:
        code = (r.get("SECURITY_CODE") or "").strip()
        if not code:
            continue
        super_net = _f(r.get("SUPERDEAL_INFLOW")) - _f(r.get("SUPERDEAL_OUTFLOW"))
        big_net = _f(r.get("BIGDEAL_INFLOW")) - _f(r.get("BIGDEAL_OUTFLOW"))
        rows.append({
            "code": code,
            "name": (r.get("SECURITY_NAME_ABBR") or "").strip(),
            "trade_date": dash_date(r.get("TRADE_DATE") or "") or snapshot_date,
            "close_price": _f(r.get("CLOSE_PRICE")),
            "pct_chg": _f(r.get("CHANGE_RATE")),
            "turnover": _f(r.get("TURNOVERRATE")),
            "main_net": _f(r.get("PRIME_INFLOW")),
            "super_net": super_net,
            "big_net": big_net,
            "mid_net": 0.0,     # 该报表不提供
            "small_net": 0.0,   # 该报表不提供
            "main_ratio": _f(r.get("RATIO")),
            "org_participate": _f(r.get("ORG_PARTICIPATE")),
            "source": "datacenter",
        })
    logger.info(f"全市场快照：{len(rows)} 只（日期 {snapshot_date}）")
    return rows, snapshot_date


def breadth_from_snapshot(rows: List[Dict]) -> Dict[str, int]:
    """由快照推导市场宽度。

    相比 push2 ulist 的指数成分口径，这里是**逐只统计**，不存在成分覆盖不全
    （深证成指仅 500 只）与指数嵌套重复计数的问题。
    """
    up = down = flat = 0
    near_up = near_down = 0
    for r in rows:
        p = r.get("pct_chg") or 0.0
        if p > 0:
            up += 1
            if p >= 9.8:
                near_up += 1
        elif p < 0:
            down += 1
            if p <= -9.8:
                near_down += 1
        else:
            flat += 1
    return {
        "up": up, "down": down, "flat": flat,
        "near_limit_up": near_up, "near_limit_down": near_down,
        "total": len(rows),
    }


async def collect_market_snapshot(trade_date: Optional[str] = None) -> Dict:
    """采集全市场快照并写入 money_flow；同时返回市场宽度。"""
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    rows, snap_date = await fetch_market_snapshot(td)
    if len(rows) < MIN_SNAPSHOT_ROWS:
        logger.warning(f"全市场快照仅 {len(rows)} 行 < 阈值 {MIN_SNAPSHOT_ROWS}，跳过写库")
        return {"rows": 0, "breadth": None, "snapshot_date": snap_date}

    n = store.upsert_money_flow(rows)
    breadth = breadth_from_snapshot(rows)
    logger.info(
        f"[{snap_date}] 资金流写入 {n} 行；市场宽度 涨 {breadth['up']} / "
        f"跌 {breadth['down']} / 平 {breadth['flat']}"
    )
    return {"rows": n, "breadth": breadth, "snapshot_date": snap_date}


def run_collect_market_snapshot(trade_date: Optional[str] = None) -> Dict:
    return asyncio.run(collect_market_snapshot(trade_date))
