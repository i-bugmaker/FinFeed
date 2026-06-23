#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻抓取引擎

负责：
- 并发抓取所有新闻源
- 速率限制与熔断
- 调用对应 Parser 解析响应
- 增量更新（记录每个源的最新时间戳）
"""

import time
import hashlib
import logging
from typing import Optional
from urllib.parse import urlencode

import httpx

from config.sources import NewsSource, get_enabled_sources
from config.settings import (
    FETCH_CONCURRENCY, SOURCE_RATE_LIMITS, SOURCE_SKIP_REQ_TRACE,
    get_source_timeout, should_skip_source,
)
from .parsers.factory import create_parser
from .parsers.base import BaseParser
from .health import get_health_monitor
from storage.models import NewsItem

logger = logging.getLogger("news_monitor")

_last_source_req: dict[str, float] = {}
_rate_blocked_until: dict[str, float] = {}
_parsers: dict[str, BaseParser] = {}


def _get_parser(source: NewsSource) -> BaseParser:
    """获取或创建源对应的 Parser"""
    if source.name not in _parsers:
        _parsers[source.name] = create_parser(source)
    return _parsers[source.name]


def init_all_parsers():
    """初始化所有 Parser（用于预加载）"""
    for src in get_enabled_sources():
        _get_parser(src)


def set_parser_last_ts(source_name: str, ts: int):
    """设置指定源的增量时间戳"""
    if source_name in _parsers:
        _parsers[source_name].last_ts = ts


def get_parser_last_ts(source_name: str) -> int:
    """获取指定源的最新时间戳"""
    if source_name in _parsers:
        return _parsers[source_name].last_ts
    return 0


async def fetch_news_from_source(
    source: NewsSource,
    client: Optional[httpx.AsyncClient] = None,
) -> list[NewsItem]:
    """从指定新闻源抓取新闻

    Args:
        source: 新闻源配置
        client: 可选的共享 httpx client

    Returns:
        新闻条目列表
    """
    news_list: list[NewsItem] = []
    source_name = source.name
    health_monitor = get_health_monitor()

    if health_monitor.is_circuit_open(source_name):
        remaining = health_monitor.get_circuit_remaining(source_name)
        logger.debug(f"{source_name} 断路器打开，跳过（剩余 {remaining}s）")
        return news_list

    blocked_until = _rate_blocked_until.get(source_name, 0)
    if blocked_until > time.time():
        remaining = int(blocked_until - time.time())
        logger.debug(f"{source_name} 仍在冷却中，跳过（剩余 {remaining}s）")
        return news_list

    ssl_ctx = source.verify_ssl
    timeout = get_source_timeout(source_name)
    start_time = time.time()

    try:
        min_interval = SOURCE_RATE_LIMITS.get(source_name, 0)
        if min_interval > 0:
            elapsed = time.time() - _last_source_req.get(source_name, 0)
            if elapsed < min_interval:
                import asyncio
                await asyncio.sleep(min_interval - elapsed)

        use_shared = client is not None
        if use_shared:
            http_client = client
        else:
            http_client = httpx.AsyncClient(
                timeout=timeout, follow_redirects=True, verify=ssl_ctx
            )

        try:
            kwargs = {"url": source.url, "headers": dict(source.headers)}
            if not ssl_ctx:
                kwargs["verify"] = False

            method = source.method
            if source.params and source_name not in SOURCE_SKIP_REQ_TRACE:
                params_dict = dict(source.params)
                if method == "GET":
                    kwargs["params"] = params_dict
                    kwargs["params"]["req_trace"] = str(int(time.time() * 1000))
                else:
                    kwargs["data"] = params_dict
            elif source.params and source_name in SOURCE_SKIP_REQ_TRACE:
                kwargs["params"] = dict(source.params)

            if source_name == "财联社":
                parser = _get_parser(source)
                last_ts = parser.last_ts
                cls_params = {
                    "app": "CailianpressWeb",
                    "os": "web",
                    "sv": "8.4.6",
                    "rn": "20",
                    "last_time": str(int(last_ts if last_ts > 0 else time.time())),
                }
                qs = urlencode(sorted(cls_params.items()))
                cls_params["sign"] = hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()
                kwargs["params"] = cls_params

            if method == "POST":
                response = await http_client.post(**kwargs)
            else:
                response = await http_client.get(**kwargs)
        finally:
            if not use_shared:
                await http_client.aclose()

        if min_interval > 0:
            _last_source_req[source_name] = time.time()

        if response.status_code == 429:
            retry_after_str = (response.headers.get("Retry-After") or "").strip()
            retry_after = int(retry_after_str) if retry_after_str.isdigit() else 60
            logger.warning(f"{source_name} 触发速率限制 (429)，冷却 {retry_after}s")
            _rate_blocked_until[source_name] = time.time() + retry_after + 30
            health_monitor.record_failure(source_name, "HTTP 429 Too Many Requests")
            return news_list

        if response.status_code != 200:
            logger.warning(f"获取{source_name}失败：HTTP {response.status_code}")
            health_monitor.record_failure(source_name, f"HTTP {response.status_code}")
            return news_list

        parser = _get_parser(source)
        news_list = await parser.parse(response)
        parser.update_last_ts(news_list)

        latency = time.time() - start_time
        health_monitor.record_success(source_name, latency)

    except httpx.ConnectTimeout:
        logger.warning(f"获取{source_name}失败：连接超时")
        health_monitor.record_failure(source_name, "ConnectTimeout")
    except httpx.ConnectError as e:
        logger.warning(f"获取{source_name}失败：连接错误 - {str(e)[:60]}")
        health_monitor.record_failure(source_name, f"ConnectError: {str(e)[:60]}")
    except Exception as e:
        logger.warning(f"获取{source_name}失败：{str(e)[:100]}")
        health_monitor.record_failure(source_name, str(e)[:200])

    return news_list


async def fetch_all_news(cycle: int = 1) -> tuple[list[NewsItem], dict[str, int]]:
    """并发抓取所有新闻源

    Args:
        cycle: 当前轮次（用于分级调度）

    Returns:
        (所有新闻列表, 各源抓取数量统计)
    """
    import asyncio

    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)
    sources = get_enabled_sources()

    async with httpx.AsyncClient(
        timeout=15.0, follow_redirects=True, verify=True,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=6),
    ) as shared_client:

        async def _fetch_with_sem(source: NewsSource):
            if should_skip_source(source.name, cycle):
                return source.name, []
            async with semaphore:
                return source.name, await fetch_news_from_source(source, shared_client)

        tasks = [asyncio.create_task(_fetch_with_sem(s)) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_news: list[NewsItem] = []
    source_stats: dict[str, int] = {}
    _seen_keys: set[tuple[str, str]] = set()

    for s, r in zip(sources, results):
        name = s.name
        if isinstance(r, tuple) and len(r) == 2:
            _name, items = r
            for item in items:
                key = (item.title, item.source)
                if key in _seen_keys:
                    continue
                _seen_keys.add(key)
                all_news.append(item)
            source_stats[name] = len(items)
        elif isinstance(r, Exception):
            source_stats[name] = 0
            logger.warning(f"抓取{name}异常: {r}")
        else:
            source_stats[name] = 0

    all_news.sort(key=lambda x: x.publish_ts, reverse=True)
    return all_news, source_stats
