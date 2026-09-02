#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日历数据异步抓取器

以「单日」为最小抓取单元，四类数据源统一暴露：

    await fetch_day(client, cal_type, date) -> list[CalendarEvent]

东财 datacenter 单页上限 500 条，超出自动翻页（最多 EM_MAX_PAGES 页）。
不接入 core/fetcher 的 5 秒主循环与熔断器 —— 日历是低频按需数据。
"""

import asyncio
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

from .models import CalendarEvent
from .parsers import parse_finance, parse_global, parse_ipo, parse_stock
from .sources import (
    EM_DATACENTER,
    EM_DATACENTER_SEC,
    EM_FOREX_CALENDAR,
    EM_MAX_PAGES,
    EM_PAGE_SIZE,
    FINANCE_COLUMNS,
    STOCK_COLUMNS,
    datacenter_headers,
    forex_headers,
)
from .sources import (
    EM_FOREX_CALENDAR as _FC,
)

logger = logging.getLogger("news_monitor")

DEFAULT_TIMEOUT = 20.0
_RE_JSONP = re.compile(r"^[^(]*\((.*)\);?\s*$", re.S)

# 持久化连接池（进程级，专治冷 DNS 卡顿）
# 痛点：本机 IPv4-only DNS 解析 eastmoney 域名约 11s，若每次
# 请求都新建 httpx.AsyncClient，则每次都会触发冷解析。
# 方案：在独立后台线程常驻一个 asyncio 事件循环 + 一个常驻
# AsyncClient，所有抓取协程都调度到该 loop 上执行，DNS 仅解析
# 一次并长期复用连接池。Web 工作线程通过 run_on_pool() 提交
# 协程并以 future.result() 同步取回结果。
_pool_lock = threading.Lock()
_pool_thread: Optional[threading.Thread] = None
_pool_loop: Optional[asyncio.AbstractEventLoop] = None
_pool_client: Optional[httpx.AsyncClient] = None
POOL_TIMEOUT = 120.0


def _pool_runner() -> None:
    """后台线程入口：常驻事件循环"""
    global _pool_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _pool_loop = loop
    try:
        loop.run_forever()
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:  # noqa: BLE001
            pass
        try:
            loop.close()
        except Exception:  # noqa: BLE001
            pass


def _ensure_pool() -> asyncio.AbstractEventLoop:
    """确保后台 loop 已启动（幂等、线程安全）"""
    global _pool_thread
    with _pool_lock:
        if _pool_thread is None:
            _pool_thread = threading.Thread(
                target=_pool_runner, name="cal-http-pool", daemon=True
            )
            _pool_thread.start()
            while _pool_loop is None:
                time.sleep(0.005)
    return _pool_loop  # type: ignore[return-value]


async def _get_client() -> httpx.AsyncClient:
    """惰性获取常驻 client（同 loop 内仅创建一次）"""
    global _pool_client
    if _pool_client is None or _pool_client.is_closed:
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
        _pool_client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, follow_redirects=True, limits=limits
        )
    return _pool_client


def run_on_pool(coro):
    """在任何线程把协程调度到常驻 loop 并同步取回结果"""
    loop = _ensure_pool()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return future.result(timeout=POOL_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        # 把协程内异常原样抛出，便于上层捕获
        raise exc


async def _warmup_coro() -> None:
    """best-effort 预解析 DNS，避免首个真实请求冷启动卡顿"""
    client = await _get_client()
    for url in (EM_DATACENTER, EM_DATACENTER_SEC, EM_FOREX_CALENDAR):
        try:
            await client.get(url, timeout=8.0)
        except Exception:  # noqa: BLE001
            pass


def warmup() -> None:
    """非阻塞预热：在后台线程触发一次 DNS 解析（可忽略失败）"""
    def _worker() -> None:
        try:
            loop = _ensure_pool()
            asyncio.run_coroutine_threadsafe(_warmup_coro(), loop).result(timeout=30)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[calendar] 预热失败（可忽略）: {type(e).__name__} {e}")

    threading.Thread(target=_worker, name="cal-warmup", daemon=True).start()


# 工具
def next_day(date: str) -> str:
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def _loads(text: str) -> Dict[str, Any]:
    """兼容裸 JSON 与 JSONP 包裹"""
    t = (text or "").strip()
    if not t:
        return {}
    if t[0] not in "{[":
        m = _RE_JSONP.match(t)
        if m:
            t = m.group(1)
    try:
        return json.loads(t)
    except (ValueError, TypeError):
        return {}


async def _dc_query(
    client: httpx.AsyncClient,
    url: str,
    params: Dict[str, Any],
    referer: str,
) -> List[Dict[str, Any]]:
    """东财 datacenter 通用查询（自动翻页）"""
    rows: List[Dict[str, Any]] = []
    page = 1
    while page <= EM_MAX_PAGES:
        p = dict(params)
        p["pageSize"] = EM_PAGE_SIZE
        p["pageNumber"] = page
        resp = await client.get(url, params=p, headers=datacenter_headers(referer))
        if resp.status_code != 200:
            logger.warning(f"[calendar] {params.get('reportName')} HTTP {resp.status_code}")
            break

        j = _loads(resp.text)
        result = j.get("result")
        if not isinstance(result, dict):
            # success=false 通常表示当日无数据
            break

        data = result.get("data") or []
        rows.extend(data)

        pages = result.get("pages") or 1
        if page >= pages or len(data) < EM_PAGE_SIZE:
            break
        page += 1

    return rows


# 1. 财经日历
async def fetch_finance(client: httpx.AsyncClient, date: str) -> List[CalendarEvent]:
    """返回在 date 当天处于进行中的财经事件（含跨天会议）"""
    params = {
        "reportName": "RPT_CPH_FECALENDAR",
        "columns": FINANCE_COLUMNS,
        "sortColumns": "START_DATE",
        "sortTypes": "1",
        "filter": f"(END_DATE>='{date}')(START_DATE<'{next_day(date)}')",
        "source": "WEB",
        "client": "WEB",
    }
    rows = await _dc_query(client, EM_DATACENTER, params, "https://data.eastmoney.com/cjrl/default.html")
    return parse_finance(rows, date)


# 2. 股市日历
async def fetch_stock(client: httpx.AsyncClient, date: str) -> List[CalendarEvent]:
    """RPT_SPECIAL_ALL 已是 5 个子类的全集，一次取回即可"""
    params = {
        "reportName": "RPT_SPECIAL_ALL",
        "columns": STOCK_COLUMNS,
        "sortColumns": "EVENT_CODE,SECURITY_CODE",
        "sortTypes": "1,1",
        "filter": f"(TRADE_DATE='{date}')",
        "source": "WEB",
        "client": "WEB",
    }
    rows = await _dc_query(client, EM_DATACENTER, params, "https://data.eastmoney.com/gsrl/default.html")
    return parse_stock(rows, date)


# 3. 新股申购日历
async def fetch_ipo(client: httpx.AsyncClient, date: str) -> List[CalendarEvent]:
    params = {
        "reportName": "RPT_IPO_CALENDAR",
        "columns": "ALL",
        "sortColumns": "TRADE_DATE,DATE_TYPE,SECURITY_CODE",
        "sortTypes": "1,1,1",
        "filter": f"(TRADE_DATE>='{date}')(TRADE_DATE<='{date}')",
        "source": "SECURITIES",
        "client": "WEB",
    }
    rows = await _dc_query(
        client, EM_DATACENTER_SEC, params,
        "https://data.eastmoney.com/xg/xg/calendar.html",
    )
    return parse_ipo(rows, date)


# 4. 全球经济日历
async def fetch_global(client: httpx.AsyncClient, date: str) -> List[CalendarEvent]:
    resp = await client.get(_FC, params={"Date": date}, headers=forex_headers())
    if resp.status_code != 200:
        logger.warning(f"[calendar] 全球经济日历 {date} HTTP {resp.status_code}")
        return []
    resp.encoding = "utf-8"
    return parse_global(resp.text, date)


FETCHERS = {
    "finance": fetch_finance,
    "stock": fetch_stock,
    "ipo": fetch_ipo,
    "global": fetch_global,
}


# 对外统一入口
async def fetch_day(
    client: httpx.AsyncClient, cal_type: str, date: str
) -> List[CalendarEvent]:
    fn = FETCHERS.get(cal_type)
    if fn is None:
        raise ValueError(f"未知日历类型: {cal_type}")
    return await fn(client, date)


async def fetch_many(
    tasks: List[tuple],
    concurrency: int = 6,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[tuple, Any]:
    """并发抓取多个 (cal_type, date)

    Returns:
        {(cal_type, date): list[CalendarEvent] | Exception}
    """
    if not tasks:
        return {}

    client = await _get_client()
    sem = asyncio.Semaphore(max(1, concurrency))
    results: Dict[tuple, Any] = {}

    async def _one(cal_type: str, date: str):
        async with sem:
            try:
                results[(cal_type, date)] = await fetch_day(client, cal_type, date)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[calendar] 抓取失败 {cal_type} {date}: {type(e).__name__} {e}")
                results[(cal_type, date)] = e

    await asyncio.gather(*(_one(t, d) for t, d in tasks))

    return results
