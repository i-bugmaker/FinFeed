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
from typing import Optional, Dict, Tuple, List
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
from storage.database import db_get_source_last_ts, db_set_source_last_ts

logger = logging.getLogger("news_monitor")


class NewsFetcher:
    """新闻抓取器"""

    def __init__(self):
        self._parsers: Dict[str, BaseParser] = {}
        self._last_source_req: Dict[str, float] = {}
        self._rate_blocked_until: Dict[str, float] = {}

    def _get_parser(self, source: NewsSource) -> BaseParser:
        """获取或创建源对应的 Parser"""
        if source.name not in self._parsers:
            self._parsers[source.name] = create_parser(source)
        return self._parsers[source.name]

    def init_all_parsers(self):
        """初始化所有 Parser（用于预加载）"""
        for src in get_enabled_sources():
            self._get_parser(src)

    def set_parser_last_ts(self, source_name: str, ts: int):
        """设置指定源的增量时间戳"""
        if source_name in self._parsers:
            self._parsers[source_name].last_ts = ts

    def get_parser_last_ts(self, source_name: str) -> int:
        """获取指定源的最新时间戳"""
        return self._parsers[source_name].last_ts if source_name in self._parsers else 0

    @staticmethod
    def _build_cls_params(parser_last_ts: int) -> Dict[str, str]:
        """构建财联社请求参数（带签名）"""
        cls_params = {
            "app": "CailianpressWeb",
            "os": "web",
            "sv": "8.4.6",
            "rn": "20",
            "last_time": str(int(parser_last_ts if parser_last_ts > 0 else time.time())),
        }
        qs = urlencode(sorted(cls_params.items()))
        cls_params["sign"] = hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()
        return cls_params

    async def _make_request(
        self,
        http_client: httpx.AsyncClient,
        source: NewsSource,
        parser: BaseParser,
    ) -> httpx.Response:
        """构建并执行HTTP请求"""
        kwargs = {"url": source.url, "headers": dict(source.headers)}
        method = source.method
        source_name = source.name

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
            kwargs["params"] = self._build_cls_params(parser.last_ts)

        if method == "POST":
            return await http_client.post(**kwargs)
        return await http_client.get(**kwargs)

    async def _handle_response(
        self,
        source_name: str,
        response: httpx.Response,
        parser: BaseParser,
        health_monitor,
        min_interval: float,
    ) -> List[NewsItem]:
        """处理HTTP响应"""
        if response.status_code == 429:
            retry_after_str = (response.headers.get("Retry-After") or "").strip()
            retry_after = int(retry_after_str) if retry_after_str.isdigit() else 60
            logger.warning(f"{source_name} 触发速率限制 (429)，冷却 {retry_after}s")
            self._rate_blocked_until[source_name] = time.time() + retry_after + 30
            health_monitor.record_failure(source_name, "HTTP 429 Too Many Requests")
            return []

        if response.status_code != 200:
            logger.warning(f"获取{source_name}失败：HTTP {response.status_code}")
            health_monitor.record_failure(source_name, f"HTTP {response.status_code}")
            return []

        if min_interval > 0:
            self._last_source_req[source_name] = time.time()

        news_list = await parser.parse(response)
        parser.update_last_ts(news_list)
        db_set_source_last_ts(source_name, parser.last_ts)

        return news_list

    async def fetch_news_from_source(
        self,
        source: NewsSource,
        client: Optional[httpx.AsyncClient] = None,
        catch_up_mode: bool = False,
    ) -> List[NewsItem]:
        """从指定新闻源抓取新闻

        Args:
            source: 新闻源配置
            client: 可选的共享 httpx client
            catch_up_mode: 是否为补抓模式

        Returns:
            新闻条目列表
        """
        news_list: List[NewsItem] = []
        source_name = source.name
        health_monitor = get_health_monitor()

        if health_monitor.is_circuit_open(source_name):
            remaining = health_monitor.get_circuit_remaining(source_name)
            logger.debug(f"{source_name} 断路器打开，跳过（剩余 {remaining}s）")
            return news_list

        blocked_until = self._rate_blocked_until.get(source_name, 0)
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
                elapsed = time.time() - self._last_source_req.get(source_name, 0)
                if elapsed < min_interval:
                    await __import__('asyncio').sleep(min_interval - elapsed)

            use_shared = client is not None and source.verify_ssl
            if use_shared:
                http_client = client
            else:
                http_client = httpx.AsyncClient(
                    timeout=timeout, follow_redirects=True, verify=ssl_ctx
                )

            try:
                parser = self._get_parser(source)

                if catch_up_mode and hasattr(parser, 'fetch_with_catch_up'):
                    parser.set_catch_up_mode(True)
                    catch_up_news = await parser.fetch_with_catch_up(http_client)
                    news_list.extend(catch_up_news)
                    parser.set_catch_up_mode(False)
                    db_set_source_last_ts(source_name, parser.last_ts)
                else:
                    response = await self._make_request(http_client, source, parser)
                    if not hasattr(response, 'client'):
                        response.client = http_client
                    news_list = await self._handle_response(
                        source_name, response, parser, health_monitor, min_interval
                    )

                latency = time.time() - start_time
                health_monitor.record_success(source_name, latency)
            finally:
                if not use_shared:
                    await http_client.aclose()

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

    async def fetch_all_news(
        self, cycle: int = 1, catch_up_mode: bool = False
    ) -> Tuple[List[NewsItem], Dict[str, int]]:
        """并发抓取所有新闻源

        Args:
            cycle: 当前轮次（用于分级调度）
            catch_up_mode: 是否为补抓模式

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
                if should_skip_source(source.name, cycle) and not catch_up_mode:
                    return source.name, []
                async with semaphore:
                    return source.name, await self.fetch_news_from_source(source, shared_client, catch_up_mode)

            tasks = [asyncio.create_task(_fetch_with_sem(s)) for s in sources]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_news: List[NewsItem] = []
        source_stats: Dict[str, int] = {}
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


_global_fetcher: Optional[NewsFetcher] = None


def get_fetcher() -> NewsFetcher:
    """获取全局抓取器单例"""
    global _global_fetcher
    if _global_fetcher is None:
        _global_fetcher = NewsFetcher()
    return _global_fetcher


def init_all_parsers():
    """初始化所有 Parser（用于预加载）"""
    get_fetcher().init_all_parsers()


def set_parser_last_ts(source_name: str, ts: int):
    """设置指定源的增量时间戳"""
    get_fetcher().set_parser_last_ts(source_name, ts)


def get_parser_last_ts(source_name: str) -> int:
    """获取指定源的最新时间戳"""
    return get_fetcher().get_parser_last_ts(source_name)


async def fetch_news_from_source(
    source: NewsSource,
    client: Optional[httpx.AsyncClient] = None,
    catch_up_mode: bool = False,
) -> List[NewsItem]:
    """从指定新闻源抓取新闻"""
    return await get_fetcher().fetch_news_from_source(source, client, catch_up_mode)


async def fetch_all_news(cycle: int = 1, catch_up_mode: bool = False) -> Tuple[List[NewsItem], Dict[str, int]]:
    """并发抓取所有新闻源"""
    return await get_fetcher().fetch_all_news(cycle, catch_up_mode)