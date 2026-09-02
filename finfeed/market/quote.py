#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市场宽度与涨停 / 跌停 / 炸板池采集

数据链路（本次重构后）：
  市场宽度 —— 主：datacenter 全市场快照逐只统计；备：push2 ulist 指数成分（仅参考）
  涨停池   —— push2ex getTopicZTPool
  跌停池   —— push2ex getTopicDTPool
  炸板池   —— push2ex getTopicZBPool（本次新增，用于计算炸板率）

⚠️ 已修复的历史缺陷：
  1. UT_TOPIC 常量被截断成 26 位 -> push2ex 恒返回 rc=205，limit_pool 长期 0 行。
  2. 跌停池套用了涨停池的字段名：DT 池没有 `zbc`/`fbt`，开板次数是 `oc`、
     连续跌停天数是 `days`，旧实现取到的永远是 0。
  3. 市场宽度用 4 个指数的 f104/f105 相加：深证成指只有 500 只成分股，
     且创业板/科创板分别是深证/上证的子集，既漏算又重复计数。

字段契约（2026-08-07 实测）：
  ZT 池: c,n,p,zdp,amount,ltsz,tshare,hs,lbc,fbt,lbt,fund,zbc,hybk,zttj{days,ct}
  DT 池: c,n,p,zdp,amount,ltsz,tshare,pe,hs,fund,lbt,fba,days,oc,hybk
  ZB 池: c,n,p,ztp,zdp,amount,ltsz,tshare,hs,fbt,zbc,zf,zs,hybk,zttj{days,ct}
  价格字段 p / ztp 单位为**厘**（1/1000 元），金额 amount/fund/ltsz/tshare 单位为元。
"""

import asyncio
import logging
from typing import Dict, List, Optional

from finfeed.storage import sentiment_store as ss
from finfeed.utils.time_utils import now_bj

from . import snapshot, store
from .client import RateLimited, get_json
from .endpoints import (
    BREADTH_FIELDS,
    PUSH2,
    PUSH2EX,
    UT,
    UT_TOPIC,
    BREADTH_INDEX_SECIds,
    compact_date,
)

logger = logging.getLogger("news_monitor")

# 方向 -> (push2ex 端点, sort 参数)
_POOL_ENDPOINT = {
    "up": ("getTopicZTPool", "fbt:asc"),
    "down": ("getTopicDTPool", "fund:asc"),
    "broken": ("getTopicZBPool", "fbt:asc"),
}

_YI = 1e8      # 亿元
_MILLI = 1e3   # 厘 -> 元


def _f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _fmt_time(v) -> str:
    """HHMMSS 整数 -> 'HH:MM:SS'（如 92500 -> 09:25:00）"""
    if not v:
        return ""
    try:
        s = f"{int(v):06d}"
        return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"
    except (TypeError, ValueError):
        return ""


# 市场宽度
async def fetch_market_breadth_push2() -> Optional[Dict[str, int]]:
    """备用链路：push2 ulist 指数成分涨跌家数。

    仅在 datacenter 快照不可用时作为**参考值**，口径不完整（见模块头注释）。
    """
    try:
        data = await get_json(
            f"{PUSH2}/ulist.np/get",
            params={
                "secids": ",".join(BREADTH_INDEX_SECIds),
                "fields": BREADTH_FIELDS, "fltt": 2, "ut": UT,
            },
            group="em_push2",
        )
        diff = (data.get("data") or {}).get("diff") or []
        up = down = flat = 0
        for item in diff:
            up += int(item.get("f104") or 0)
            down += int(item.get("f105") or 0)
            flat += int(item.get("f106") or 0)
        if up == 0 and down == 0:
            return None
        return {"up": up, "down": down, "flat": flat, "total": up + down + flat}
    except RateLimited as e:
        logger.info(f"市场宽度备用链路跳过：{e}")
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"市场宽度备用链路失败: {e}")
        return None


# 涨跌停 / 炸板池
async def fetch_limit_pool(trade_date: str, direction: str = "up") -> List[Dict]:
    """拉取涨停 / 跌停 / 炸板池。

    Args:
        trade_date: 'YYYY-MM-DD'（内部自动转 push2ex 要求的 YYYYMMDD）
        direction: 'up' 涨停 / 'down' 跌停 / 'broken' 炸板
    """
    if direction not in _POOL_ENDPOINT:
        raise ValueError(f"未知方向: {direction}")
    endpoint, sort = _POOL_ENDPOINT[direction]
    td_compact = compact_date(trade_date)

    try:
        data = await get_json(
            f"{PUSH2EX}/{endpoint}",
            params={
                "dpt": "wz.ztzt", "Pageindex": 0, "pagesize": 1000,
                "sort": sort, "date": td_compact, "ut": UT_TOPIC,
            },
            group="em_push2ex",
        )
    except RateLimited as e:
        logger.info(f"{direction} 池跳过（冷却中）：{e}")
        return []
    except Exception as e:  # noqa: BLE001
        logger.warning(f"{direction} 池获取失败（降级跳过）: {e}")
        return []

    pool = (data.get("data") or {}).get("pool") or []
    out: List[Dict] = []
    for it in pool:
        code = str(it.get("c") or "").strip()
        if not code:
            continue
        zttj = it.get("zttj") or {}
        if direction == "down":
            # DT 池：无 fbt/zbc/lbc，用 oc(开板次数) 与 days(连续跌停天数)
            open_times = int(it.get("oc") or 0)
            streak = int(it.get("days") or 0)
            first_t, last_t = "", _fmt_time(it.get("lbt"))
        elif direction == "broken":
            # ZB 池：zbc 炸板次数，zttj.days 此前连板天数
            open_times = int(it.get("zbc") or 0)
            streak = int(zttj.get("days") or 0)
            first_t, last_t = _fmt_time(it.get("fbt")), ""
        else:
            # ZT 池：lbc 连板数（优先），zttj.days 兜底；zbc 炸板次数
            open_times = int(it.get("zbc") or 0)
            streak = int(it.get("lbc") or zttj.get("days") or 0)
            first_t, last_t = _fmt_time(it.get("fbt")), _fmt_time(it.get("lbt"))

        out.append({
            "trade_date": trade_date,
            "code": code,
            "name": (it.get("n") or "").strip(),
            "direction": direction,
            "first_limit_time": first_t,
            "last_limit_time": last_t,
            "open_times": open_times,
            "limit_streak": streak,
            "limit_amount": _f(it.get("fund")) / _YI,   # 封单额（亿元）
            "circ_mv": _f(it.get("ltsz")) / _YI,        # 流通市值（亿元）
            "total_mv": _f(it.get("tshare")) / _YI,     # 总市值（亿元）
            "amount": _f(it.get("amount")) / _YI,       # 成交额（亿元）
            "price": _f(it.get("p")) / _MILLI,          # 最新价（元）
            "pct_chg": _f(it.get("zdp")),               # 涨跌幅 %
            "turnover": _f(it.get("hs")),               # 换手率 %
            "reason": (it.get("hybk") or "").strip(),   # 所属行业板块
        })
    return out


# 盘后编排
async def collect_daily_market(trade_date: Optional[str] = None) -> Dict:
    """盘后采集：全市场快照（资金流+宽度）+ 涨停/跌停/炸板池，填充 market_sentiment_daily。"""
    td = trade_date or now_bj().strftime("%Y-%m-%d")

    # 1. 全市场快照（datacenter 主链路，一次拿到资金流 + 市场宽度）
    snap = await snapshot.collect_market_snapshot(td)
    breadth = snap.get("breadth")
    breadth_source = "datacenter"
    if not breadth:
        breadth = await fetch_market_breadth_push2()
        breadth_source = "push2(参考)" if breadth else "unavailable"

    # 2. 三个池子
    zt = await fetch_limit_pool(td, "up")
    dt = await fetch_limit_pool(td, "down")
    zb = await fetch_limit_pool(td, "broken")

    for rows in (zt, dt, zb):
        if rows:
            store.upsert_limit_pool(rows)

    zt_count, dt_count, zb_count = len(zt), len(dt), len(zb)
    # 炸板率 = 炸板数 / (涨停数 + 炸板数)，衡量封板质量
    denom = zt_count + zb_count
    broken_rate = round(zb_count / denom * 100, 2) if denom else 0.0
    # 连板高度
    max_streak = max((r["limit_streak"] for r in zt), default=0)

    breadth_up = breadth["up"] if breadth else 0
    breadth_down = breadth["down"] if breadth else 0

    ss.upsert_market_sentiment(
        trade_date=td,
        up_limit=zt_count,
        down_limit=dt_count,
        breadth=breadth_up,
    )
    logger.info(
        f"[{td}] 涨停 {zt_count} / 跌停 {dt_count} / 炸板 {zb_count}"
        f"（炸板率 {broken_rate}%，最高 {max_streak} 连板）；"
        f"市场宽度[{breadth_source}] 涨 {breadth_up} / 跌 {breadth_down}"
    )
    return {
        "up_limit": zt_count, "down_limit": dt_count, "broken": zb_count,
        "broken_rate": broken_rate, "max_streak": max_streak,
        "breadth_up": breadth_up, "breadth_down": breadth_down,
        "breadth_source": breadth_source,
        "money_flow_rows": snap.get("rows", 0),
        "zt_count": zt_count, "dt_count": dt_count,
    }


def run_collect_daily_market(trade_date: Optional[str] = None) -> Dict:
    return asyncio.run(collect_daily_market(trade_date))
