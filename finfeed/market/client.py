#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东方财富事实层 —— 统一 HTTP 客户端

设计要点：
- 按事件循环复用 httpx.AsyncClient（避免跨 loop 的 "Future attached to a different loop"）。
- 按主机自动注入 Referer（免检关键），由 endpoints.HOST_REFERER 统一维护。
- 分端点组令牌桶限速（GROUP_MIN_INTERVAL）。
- **组级冷却熔断**：东财限流是滑动窗口，惩罚期内继续探测会不断续期。
  连续 N 次网络级失败后整组静默 M 秒，期间直接短路，不发出任何请求。
- push2 / push2his / clist 网络级失败**不重试**（重试等于加重限流）。
- 复用 core/health 把每个端点组注册为独立「源」，失败即记录，连续失败开熔断。
"""

import asyncio
import logging
import threading
import time
from typing import Any, Dict, List, Optional

import httpx

from .endpoints import (
    DATACENTER,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_COOLDOWN_THRESHOLD,
    DEFAULT_PAGE_SIZE,
    DEFAULT_UA,
    GROUP_COOLDOWN_SECONDS,
    GROUP_COOLDOWN_THRESHOLD,
    GROUP_MIN_INTERVAL,
    GROUP_SOURCE_NAME,
    HARD_PAGE_CAP,
    HOST_REFERER,
    NO_RETRY_GROUPS,
    RP_PAGE_SIZE,
)

logger = logging.getLogger("news_monitor")

_MAX_RETRIES = 3
_BACKOFF = (2, 4, 8)


class RateLimited(RuntimeError):
    """端点组处于限流冷却期（调用方应降级，而非重试）。"""


# 限速 / 冷却状态用 threading.Lock 保护（事件循环无关，可跨线程）
_state_lock = threading.Lock()
_last_call: Dict[str, float] = {g: 0.0 for g in GROUP_MIN_INTERVAL}
_fail_streak: Dict[str, int] = {g: 0 for g in GROUP_MIN_INTERVAL}
_cooldown_until: Dict[str, float] = {g: 0.0 for g in GROUP_MIN_INTERVAL}

_client: Optional[httpx.AsyncClient] = None
_client_loop: Optional[asyncio.AbstractEventLoop] = None


# ---------------------------------------------------------------------------
# 客户端生命周期
# ---------------------------------------------------------------------------
def _get_client() -> httpx.AsyncClient:
    """按事件循环创建/复用客户端（不同线程的 asyncio.run 各自独立连接池）。"""
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client.is_closed or _client_loop is not loop:
        _client = httpx.AsyncClient(
            timeout=25.0, follow_redirects=True,
            headers={"User-Agent": DEFAULT_UA},
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )
        _client_loop = loop
    return _client


async def aclose() -> None:
    """关闭共享客户端（进程退出时调用）"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


def _referer_for(url: str) -> str:
    for host, ref in HOST_REFERER.items():
        if host in url:
            return ref
    return "https://quote.eastmoney.com/"


# ---------------------------------------------------------------------------
# 限速 / 冷却
# ---------------------------------------------------------------------------
async def _throttle(group: str) -> None:
    interval = GROUP_MIN_INTERVAL.get(group, 1.0)
    with _state_lock:
        last = _last_call.get(group, 0.0)
        _last_call[group] = time.monotonic()
    wait = interval - (time.monotonic() - last)
    if wait > 0:
        await asyncio.sleep(wait)


def cooldown_remaining(group: str) -> float:
    """该端点组剩余冷却秒数（0 表示可用）。"""
    with _state_lock:
        return max(0.0, _cooldown_until.get(group, 0.0) - time.monotonic())


def _note_failure(group: str) -> None:
    """记一次网络级失败；达到阈值则整组进入冷却。"""
    threshold = GROUP_COOLDOWN_THRESHOLD.get(group, DEFAULT_COOLDOWN_THRESHOLD)
    seconds = GROUP_COOLDOWN_SECONDS.get(group, DEFAULT_COOLDOWN_SECONDS)
    with _state_lock:
        _fail_streak[group] = _fail_streak.get(group, 0) + 1
        streak = _fail_streak[group]
        if streak >= threshold:
            _cooldown_until[group] = time.monotonic() + seconds
            _fail_streak[group] = 0
    if streak >= threshold:
        logger.warning(
            f"[{group}] 连续 {threshold} 次网络失败，判定为限流，静默冷却 {seconds:.0f}s"
            f"（期间该组请求直接降级，不再发包）"
        )


def _note_success(group: str) -> None:
    with _state_lock:
        _fail_streak[group] = 0


def reset_cooldown(group: Optional[str] = None) -> None:
    """手动清除冷却（测试 / 运维用）。"""
    with _state_lock:
        targets = [group] if group else list(_cooldown_until)
        for g in targets:
            _cooldown_until[g] = 0.0
            _fail_streak[g] = 0


def group_status() -> Dict[str, Dict[str, Any]]:
    """各端点组当前健康快照（供 CLI / Web 巡检展示）。"""
    now = time.monotonic()
    with _state_lock:
        return {
            g: {
                "fail_streak": _fail_streak.get(g, 0),
                "cooldown_remaining": round(max(0.0, _cooldown_until.get(g, 0.0) - now), 1),
                "min_interval": GROUP_MIN_INTERVAL.get(g, 1.0),
            }
            for g in GROUP_MIN_INTERVAL
        }


# ---------------------------------------------------------------------------
# 核心请求
# ---------------------------------------------------------------------------
async def get_json(
    url: str,
    params: Optional[dict] = None,
    group: str = "em_push2",
    timeout: float = 25.0,
    extra_headers: Optional[Dict[str, str]] = None,
) -> dict:
    """GET 并解析 JSON，内置限速 / 冷却 / 重试 / 熔断。

    Returns:
        dict。业务级拒绝（rc!=0 / success=false）返回 {}，属正常降级。
    Raises:
        RateLimited: 端点组处于冷却期（调用方应静默降级）。
        RuntimeError: 熔断开启或重试耗尽。
    """
    from finfeed.core.health import get_health_monitor
    hm = get_health_monitor()
    source = GROUP_SOURCE_NAME.get(group, group)

    remaining = cooldown_remaining(group)
    if remaining > 0:
        raise RateLimited(f"{source} 冷却中，剩余 {remaining:.0f}s")
    if hm.is_circuit_open(source):
        raise RateLimited(f"circuit open: {source}")

    no_retry = group in NO_RETRY_GROUPS
    attempts = 1 if no_retry else _MAX_RETRIES

    await _throttle(group)
    client = _get_client()
    last_err: Optional[Exception] = None

    for attempt in range(attempts):
        t0 = time.monotonic()
        try:
            headers = {
                "User-Agent": DEFAULT_UA,
                "Referer": _referer_for(url),
                "Accept": "*/*",
            }
            if extra_headers:
                headers.update(extra_headers)
            resp = await client.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            # 业务级拒绝（rc!=0 / success=false）：不是网络故障，重试无意义；
            # 记为降级空数据，不污染熔断器与冷却计数。
            if isinstance(data, dict):
                rc = data.get("rc")
                if rc is not None and rc != 0:
                    logger.warning(f"{source} 业务拒绝 rc={rc}（降级为空） {url}")
                    _note_success(group)
                    return {}
                if "success" in data and data.get("success") is False:
                    logger.warning(
                        f"{source} 业务拒绝 success=false msg={data.get('message')}"
                        f"（降级为空） {url}"
                    )
                    _note_success(group)
                    return {}
            hm.record_success(source, time.monotonic() - t0)
            _note_success(group)
            return data
        except Exception as e:  # noqa: BLE001
            last_err = e
            hm.record_failure(source, str(e)[:200])
            _note_failure(group)
            if cooldown_remaining(group) > 0:
                break  # 已进入冷却，立即停止，不再施压
            if attempt < attempts - 1:
                await asyncio.sleep(_BACKOFF[attempt])
    raise RuntimeError(f"{source} 请求失败: {last_err}") from last_err


# ---------------------------------------------------------------------------
# 会话预热（建立目标站 Cookie，避免首请求被拒）
# ---------------------------------------------------------------------------
async def warm(url: str, referer: str, group: str = "ths", timeout: float = 15.0) -> Optional[int]:
    """对目标域做一次轻量 GET 以写入会话 Cookie（不解析 JSON）。

    同花顺移动版接口要求预先访问根域建立 Cookie，否则 dataapi/mobileapi
    可能直接拒绝。返回 HTTP 状态码；冷却期或失败时返回 None（不影响主链路）。
    """
    remaining = cooldown_remaining(group)
    if remaining > 0:
        return None
    client = _get_client()
    try:
        resp = await client.get(
            url, headers={"User-Agent": DEFAULT_UA, "Referer": referer}, timeout=timeout
        )
        return resp.status_code
    except Exception as e:  # noqa: BLE001
        logger.debug("warm %s 失败（不影响主链路）: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# datacenter 统一分页器（事实层主力链路）
# ---------------------------------------------------------------------------
async def datacenter_pages(
    report_name: str,
    columns: str = "ALL",
    filter_expr: str = "",
    sort_columns: str = "",
    sort_types: int = -1,
    page_size: Optional[int] = None,
    max_pages: int = 60,
    extra: Optional[dict] = None,
    probe: bool = False,
) -> List[Dict[str, Any]]:
    """按报表的服务端 pageSize 上限自动分页抓全量。

    ⚠️ 不同报表的 pageSize 上限不同（如 RPT_DMSK_TS_STOCKNEW 硬限 500），
       超限会被**静默截断**而非报错，必须按 RP_PAGE_SIZE 取值，否则数据缺失无感知。

    filter 表达式一律使用单引号，例如 "(TRADE_DATE='2026-08-07')"。
    httpx 会自动做百分号编码；切勿手工拼 URL 时保留裸双引号（Tomcat 会回 400）。
    """
    ps = page_size or RP_PAGE_SIZE.get(report_name, DEFAULT_PAGE_SIZE)
    out: List[Dict[str, Any]] = []
    total: Optional[int] = None
    page = 0
    page_cap = max_pages
    ps_corrected = False

    while page < page_cap:
        page += 1
        params: Dict[str, Any] = {
            "pageNumber": page, "pageSize": ps, "columns": columns,
            "reportName": report_name, "source": "WEB", "client": "WEB",
        }
        if sort_columns:
            params["sortColumns"] = sort_columns
            params["sortTypes"] = sort_types
        if filter_expr:
            params["filter"] = filter_expr
        if extra:
            params.update(extra)

        data = await get_json(DATACENTER, params=params, group="em_datacenter")
        result = data.get("result") or {}
        if total is None:
            total = result.get("count") or 0
        batch = result.get("data") or []
        out.extend(batch)

        # 空页 = 真末页
        if not batch:
            break

        # ⚠️ 服务端 pageSize 截断自愈：
        # 首页请求 5000 却只回 500，说明该报表硬限 500。旧实现在此处误判末页
        # （len(batch) < ps → break），会静默丢掉 88% 的数据且无任何报错。
        # 这里改为：以 count 为准，把 ps 校正为服务端真实上限并按比例放宽页数上限。
        if page == 1 and total and len(batch) < ps and len(batch) < total:
            if not ps_corrected:
                real_ps = len(batch)
                # ⚠️ 硬上限保护：部分报表 count 是**全历史**规模（如
                # RPT_VALUEANALYSIS_DET count=934 万），若无条件按 count 放大页数
                # 会产生上千次请求并打爆采集。这里封顶 HARD_PAGE_CAP。
                needed = -(-total // real_ps) + 1
                page_cap = min(max(page_cap, needed), HARD_PAGE_CAP)
                logger.warning(
                    f"[{report_name}] pageSize 被服务端截断 {ps}→{real_ps}，"
                    f"已自动校正（count={total}，页数上限 {page_cap}"
                    f"{'，已触顶 HARD_PAGE_CAP，结果可能不完整' if needed > HARD_PAGE_CAP else ''}）。"
                    f"建议在 endpoints.RP_PAGE_SIZE 中登记该上限。"
                )
                ps = real_ps
                ps_corrected = True
            continue

        # 正常终止：已取满 count
        if total and len(out) >= total:
            break
        # 无 count 的报表：短页即末页
        if not total and len(batch) < ps:
            break
    else:
        if not probe:
            logger.warning(f"[{report_name}] 达到分页上限 {page_cap}，可能未取全（已取 {len(out)}）")

    if total and len(out) < total and not probe:
        logger.warning(f"[{report_name}] 期望 {total} 条，实取 {len(out)} 条")
    return out
