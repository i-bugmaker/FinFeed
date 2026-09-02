#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日历服务编排

职责：
  1. 按「类型 + 日期」判定缓存新鲜度（TTL 随日期远近分级）
  2. 并发拉取过期/缺失的日期，归一化后覆盖入库
  3. 对外提供同步阻塞式查询接口，供 http.server 工作线程直接调用

线程模型：
  Web 服务是 ThreadingHTTPServer，每个请求在独立线程中处理。
  并发抓取统一调度到 fetcher 内常驻的「连接池线程 + 事件循环 +
  AsyncClient」，DNS 仅解析一次并长期复用连接池，根治冷启动卡顿，
  与 monitor 主循环的事件循环互不干扰。
  同一 (type, date) 的并发抓取由 _inflight 锁去重。
"""

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from finfeed.utils.time_utils import now_bj

from . import store
from .fetcher import fetch_many, run_on_pool
from .schema import ensure_tables
from .sources import CAL_TYPE_KEYS

logger = logging.getLogger("news_monitor")

# 参数
# TTL 分级（秒）：越接近当下，数据变动越频繁
TTL_SETTLED = 30 * 86400   # 3 天前：已定型
TTL_RECENT = 30 * 60       # 近 3 天 ~ 明天：30 分钟
TTL_FUTURE = 6 * 3600      # 后天及以后：6 小时

MAX_SYNC_DAYS_SINGLE = 62  # 单类型单次最多同步天数
MAX_SYNC_DAYS_ALL = 31     # 全类型聚合时的天数上限
MAX_RANGE_DAYS = 366       # 查询区间硬上限

FETCH_CONCURRENCY = 6

_inflight: Dict[Tuple[str, str], threading.Event] = {}
_inflight_lock = threading.Lock()


# 日期工具
def today_str() -> str:
    return now_bj().strftime("%Y-%m-%d")


def _parse(d: str) -> Optional[datetime]:
    try:
        return datetime.strptime(d[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def date_range(start: str, end: str, cap: int = MAX_RANGE_DAYS) -> List[str]:
    """生成 [start, end] 的日期列表（含端点）"""
    s, e = _parse(start), _parse(end)
    if not s or not e:
        return []
    if e < s:
        s, e = e, s
    days = (e - s).days + 1
    days = min(days, cap)
    return [(s + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]


def normalize_range(start: str, end: str) -> Tuple[str, str]:
    t = today_str()
    s = start if _parse(start) else t
    e = end if _parse(end) else s
    if _parse(e) < _parse(s):
        s, e = e, s
    return s, e


def _ttl_for(date: str, today: str) -> int:
    ds, ts_ = _parse(date), _parse(today)
    if not ds or not ts_:
        return TTL_RECENT
    delta = (ds - ts_).days
    if delta < -3:
        return TTL_SETTLED
    if delta <= 1:
        return TTL_RECENT
    return TTL_FUTURE


# 同步
def _stale_dates(cal_type: str, dates: List[str], force: bool) -> List[str]:
    if force:
        return list(dates)
    today = today_str()
    sync_map = store.get_sync_map(cal_type, dates)
    now = int(time.time())
    stale = []
    for d in dates:
        ts_, status = sync_map.get(d, (0, ""))
        if not ts_:
            stale.append(d)
            continue
        ttl = _ttl_for(d, today)
        if status != "ok":
            ttl = min(ttl, 300)  # 上次失败：5 分钟后重试
        if now - ts_ > ttl:
            stale.append(d)
    return stale


def _acquire(keys: List[Tuple[str, str]]) -> Tuple[List[Tuple[str, str]], List[threading.Event]]:
    """抢占抓取权；已被其他线程占用的返回其 Event 供等待"""
    mine, waits = [], []
    with _inflight_lock:
        for k in keys:
            ev = _inflight.get(k)
            if ev is None:
                _inflight[k] = threading.Event()
                mine.append(k)
            else:
                waits.append(ev)
    return mine, waits


def _release(keys: List[Tuple[str, str]]) -> None:
    with _inflight_lock:
        for k in keys:
            ev = _inflight.pop(k, None)
            if ev is not None:
                ev.set()


def _run_async(coro):
    """执行协程：统一调度到常驻连接池的 loop 上（避免每次冷 DNS）

    优先直接提交到常驻 loop；若调用方自身已处于某个事件循环内
    （极端情况），则丢到后台线程执行以免阻塞当前 loop。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run_on_pool(coro)

    box: Dict[str, Any] = {}
    err: Dict[str, Exception] = {}

    def _worker():
        try:
            box["r"] = run_on_pool(coro)
        except Exception as e:  # noqa: BLE001
            err["e"] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()
    if "e" in err:
        raise err["e"]
    return box.get("r")


def sync_range(
    cal_types: List[str],
    start: str,
    end: str,
    force: bool = False,
) -> Dict[str, Any]:
    """确保 [start, end] 区间内指定类型的数据是新鲜的

    Returns:
        {"fetched": n, "days": n, "errors": [...], "elapsed_ms": n}
    """
    ensure_tables()
    t0 = time.time()

    cap = MAX_SYNC_DAYS_ALL if len(cal_types) > 1 else MAX_SYNC_DAYS_SINGLE
    dates = date_range(start, end, cap=cap)
    if not dates:
        return {"fetched": 0, "days": 0, "errors": ["invalid date range"], "elapsed_ms": 0}

    tasks: List[Tuple[str, str]] = []
    for ct in cal_types:
        for d in _stale_dates(ct, dates, force):
            tasks.append((ct, d))

    if not tasks:
        return {"fetched": 0, "days": len(dates), "errors": [], "elapsed_ms": 0, "cached": True}

    mine, waits = _acquire(tasks)

    fetched = 0
    errors: List[str] = []
    try:
        if mine:
            results = _run_async(fetch_many(mine, concurrency=FETCH_CONCURRENCY))
            for (ct, d), res in results.items():
                if isinstance(res, Exception):
                    store.mark_synced(ct, d, 0, status="error", err=f"{type(res).__name__}: {res}")
                    errors.append(f"{ct}/{d}: {type(res).__name__}")
                    continue
                try:
                    n = store.replace_day(ct, d, res)
                    store.mark_synced(ct, d, n, status="ok")
                    fetched += n
                except Exception as e:  # noqa: BLE001
                    logger.error(f"[calendar] 入库失败 {ct} {d}: {e}")
                    store.mark_synced(ct, d, 0, status="error", err=str(e))
                    errors.append(f"{ct}/{d}: db")
    finally:
        _release(mine)

    # 等待其他线程正在抓的相同日期
    for ev in waits:
        ev.wait(timeout=25)

    return {
        "fetched": fetched,
        "days": len(dates),
        "tasks": len(tasks),
        "errors": errors,
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


# 查询
def get_events(
    cal_type: str = "finance",
    start: str = "",
    end: str = "",
    category: str = "",
    region: str = "",
    keyword: str = "",
    importance_min: int = 0,
    limit: int = 3000,
    offset: int = 0,
    refresh: bool = False,
    sync: bool = True,
) -> Dict[str, Any]:
    """按日期区间查询日历事件（自动同步缺失数据）"""
    ensure_tables()
    start, end = normalize_range(start, end)

    types = CAL_TYPE_KEYS if cal_type == "all" else [cal_type]
    sync_info: Dict[str, Any] = {}
    if sync:
        sync_info = sync_range(types, start, end, force=refresh)

    res = store.query_events(
        cal_type=cal_type, start=start, end=end, category=category,
        region=region, keyword=keyword, importance_min=importance_min,
        limit=limit, offset=offset,
    )

    return {
        "cal_type": cal_type,
        "start": start,
        "end": end,
        "total": res["total"],
        "items": res["items"],
        "sync": sync_info,
    }


def get_month(cal_type: str, month: str, refresh: bool = False) -> Dict[str, Any]:
    """月历视图：返回该月每天的事件计数

    Args:
        month: YYYY-MM
    """
    ensure_tables()
    m = month if len(month) == 7 else today_str()[:7]
    try:
        first = datetime.strptime(m + "-01", "%Y-%m-%d")
    except ValueError:
        first = datetime.strptime(today_str()[:7] + "-01", "%Y-%m-%d")

    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    last = nxt - timedelta(days=1)
    start, end = first.strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d")

    types = CAL_TYPE_KEYS if cal_type == "all" else [cal_type]
    sync_info = sync_range(types, start, end, force=refresh)
    counts = store.count_by_date(cal_type, start, end)

    return {
        "cal_type": cal_type,
        "month": m,
        "start": start,
        "end": end,
        "first_weekday": first.weekday(),   # 0=周一
        "days": last.day,
        "counts": counts,
        "sync": sync_info,
    }


def get_overview(date: str = "", refresh: bool = False) -> Dict[str, Any]:
    """单日总览：四类日历各自的事件"""
    ensure_tables()
    d = date if _parse(date) else today_str()
    sync_info = sync_range(CAL_TYPE_KEYS, d, d, force=refresh)

    blocks = {}
    for ct in CAL_TYPE_KEYS:
        r = store.query_events(cal_type=ct, start=d, end=d, limit=2000)
        blocks[ct] = {"total": r["total"], "items": r["items"]}

    return {"date": d, "blocks": blocks, "sync": sync_info}
