#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻解析器基类

策略模式：每个新闻源对应一个 Parser 子类，负责将 HTTP 响应解析为 NewsItem 列表。
"""

import re
import time
import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any

import httpx
from bs4 import BeautifulSoup

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import ts_from_bj_str, bj_str_from_ts, now_bj, parse_relative_time
from finfeed.utils.http_utils import strip_html
from finfeed.config.sources import NewsSource, get_source_category
from finfeed.config.settings import get_display_name, CATCH_UP_MAX_DAYS

logger = logging.getLogger("news_monitor")

CATCH_UP_MIN_INTERVAL = 0.3

_PARSER_REGISTRY: Dict[str, type] = {}


def register_parser(parser_type: str):
    """解析器注册装饰器
    
    使用方法:
        @register_parser("sina")
        class SinaParser(BaseParser):
            ...
    """
    def decorator(cls):
        _PARSER_REGISTRY[parser_type] = cls
        return cls
    return decorator


def get_registered_parsers() -> Dict[str, type]:
    """获取所有已注册的解析器"""
    return dict(_PARSER_REGISTRY)


class BaseParser(ABC):
    """解析器基类"""

    def __init__(self, source: NewsSource):
        self.source = source
        self.last_ts: int = 0
        self._catch_up_mode = False
        self._catch_up_end_ts = 0

    def set_catch_up_mode(self, enabled: bool, end_ts: int = 0):
        """设置补抓模式"""
        self._catch_up_mode = enabled
        self._catch_up_end_ts = end_ts

    def get_catch_up_start_ts(self) -> int:
        """获取补抓起始时间戳（最多回溯7天）"""
        if self.last_ts <= 0:
            return int(time.time()) - CATCH_UP_MAX_DAYS * 24 * 3600
        max_back_ts = int(time.time()) - CATCH_UP_MAX_DAYS * 24 * 3600
        return max(self.last_ts, max_back_ts)

    @abstractmethod
    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        """解析 HTTP 响应，返回新闻列表"""
        pass

    def _get_logger(self):
        """获取日志记录器"""
        return logger

    async def _paginated_fetch(
        self,
        http_client,
        url: str,
        params: Dict[str, Any],
        page_param: str = "page",
        max_pages: int = 15,
        items_per_page: int = 20,
        sleep_interval: float = CATCH_UP_MIN_INTERVAL,
    ) -> list[NewsItem]:
        """通用分页补抓方法

        Args:
            http_client: HTTP客户端
            url: 请求URL
            params: 请求参数（不含分页参数）
            page_param: 分页参数名（默认为"page"）
            max_pages: 最大页数
            items_per_page: 每页条数
            sleep_interval: 每页请求间隔

        Returns:
            所有页的新闻列表
        """
        all_news = []
        page_num = 1
        logger = self._get_logger()
        catch_up_start_ts = self.get_catch_up_start_ts()

        saved_last_ts = self.last_ts
        self.last_ts = 0

        try:
            while page_num <= max_pages:
                try:
                    page_params = dict(params)
                    page_params[page_param] = page_num

                    if self.source.method == "POST":
                        resp = await http_client.post(
                            url,
                            headers=dict(self.source.headers),
                            data=page_params
                        )
                    else:
                        resp = await http_client.get(
                            url,
                            headers=dict(self.source.headers),
                            params=page_params
                        )

                    if resp.status_code != 200:
                        logger.warning(f"{self.source.name} 补抓请求失败：HTTP {resp.status_code}")
                        break

                    news_list = await self.parse(resp)
                    if not news_list:
                        break

                    all_news.extend(news_list)

                    oldest_ts = min((n.publish_ts for n in news_list if n.publish_ts > 0), default=int(time.time()))
                    if oldest_ts <= catch_up_start_ts:
                        break

                    if len(news_list) < items_per_page:
                        break

                    page_num += 1
                    await asyncio.sleep(sleep_interval)

                except Exception as e:
                    logger.warning(f"{self.source.name} 补抓失败：{str(e)[:80]}")
                    break
        finally:
            self.last_ts = saved_last_ts

        filtered = [n for n in all_news if n.publish_ts > catch_up_start_ts]
        if filtered:
            self.last_ts = max(n.publish_ts for n in filtered if n.publish_ts > 0)

        return filtered

    async def _catch_up_single_request(self, http_client, url: str, params: Optional[Dict[str, Any]] = None) -> list[NewsItem]:
        """单次请求补抓（适用于不支持分页的源）

        Args:
            http_client: HTTP客户端
            url: 请求URL
            params: 请求参数

        Returns:
            新闻列表（过滤掉已抓取的）
        """
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        try:
            if params is None:
                params = {}

            if self.source.method == "POST":
                resp = await http_client.post(
                    url,
                    headers=dict(self.source.headers),
                    data=params
                )
            else:
                resp = await http_client.get(
                    url,
                    headers=dict(self.source.headers),
                    params=params
                )

            if resp.status_code != 200:
                return []

            news_list = await self.parse(resp)
            catch_up_start_ts = self.get_catch_up_start_ts()
            filtered = [n for n in news_list if n.publish_ts > catch_up_start_ts]

            if filtered:
                self.last_ts = max(n.publish_ts for n in filtered if n.publish_ts > 0)

            return filtered

        except Exception:
            return []

    async def _catch_up_paginated(
        self,
        http_client,
        url: str,
        params: Dict[str, Any],
        page_param: str = "page",
        max_pages: int = 15,
        items_per_page: int = 20,
        sleep_interval: float = CATCH_UP_MIN_INTERVAL,
    ) -> list[NewsItem]:
        """通用分页补抓（带完整的补抓流程处理）

        Args:
            http_client: HTTP客户端
            url: 请求URL
            params: 请求参数（不含分页参数）
            page_param: 分页参数名（默认为"page"）
            max_pages: 最大页数
            items_per_page: 每页条数
            sleep_interval: 每页请求间隔

        Returns:
            新闻列表（过滤掉已抓取的）
        """
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        logger = self._get_logger()
        logger.info(f"{self.source.name}补抓模式：开始分页补抓")

        filtered = await self._paginated_fetch(
            http_client, url, params, page_param, max_pages, items_per_page, sleep_interval
        )

        filtered.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"{self.source.name}补抓完成：共获取{len(filtered)}条历史新闻")

        return filtered

    def _make_news(self, title: str, url: str = "#", publish_ts: int = 0,
                    publish_time: str = "", intro: str = "",
                    source_name: Optional[str] = None) -> NewsItem:
        """构造 NewsItem 对象"""
        if not publish_time:
            publish_time = bj_str_from_ts(publish_ts) if publish_ts else now_bj().strftime("%Y-%m-%d %H:%M:%S")
        return NewsItem(
            title=title[:80] if len(title) > 80 else title,
            url=url or "#",
            source=source_name or get_display_name(self.source.name),
            publish_time=publish_time,
            publish_ts=publish_ts,
            intro=intro[:150] if len(intro) > 150 else intro,
            # 分类标签按来源归属：快讯源 -> "flash"，文章来源 -> "article"。
            # 论坛(UGC)解析器不经过本方法（使用 forum_parsers/base.py 的 _build_news_item，
            # 固定 category="forum"），因此此处仅会出现 flash / article 两种取值。
            category=get_source_category(self.source.name),
        )

    def _is_newer_than_last(self, ts: int) -> bool:
        """判断时间戳是否比上次更新"""
        return ts > self.last_ts

    def update_last_ts(self, news_list: list[NewsItem]):
        """更新最新时间戳"""
        timestamps = [n.publish_ts for n in news_list if n.publish_ts > 0]
        if timestamps:
            self.last_ts = max(timestamps)
