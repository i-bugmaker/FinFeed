#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻解析器基类

策略模式：每个新闻源对应一个 Parser 子类，负责将 HTTP 响应解析为 NewsItem 列表。
"""

import re
import time
import asyncio
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any

import httpx
from bs4 import BeautifulSoup

from storage.models import NewsItem
from utils.time_utils import ts_from_bj_str, bj_str_from_ts, now_bj, parse_relative_time
from utils.http_utils import strip_html
from config.sources import NewsSource
from config.settings import get_display_name, CATCH_UP_MAX_DAYS

CATCH_UP_MIN_INTERVAL = 0.3


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

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：获取历史数据（默认实现为空，子类可覆盖）"""
        return []

    def _get_logger(self):
        """获取日志记录器"""
        return __import__('logging').getLogger("news_monitor")

    async def _paginated_fetch(
        self,
        http_client,
        url: str,
        params: Dict[str, Any],
        page_param: str = "page",
        max_pages: int = 50,
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
                logger.debug(f"{self.source.name} 补抓：第{page_num}页，新增{len(news_list)}条")

                if len(news_list) < items_per_page:
                    break

                page_num += 1
                await asyncio.sleep(sleep_interval)

            except Exception as e:
                logger.warning(f"{self.source.name} 补抓失败：{str(e)[:80]}")
                break

        return all_news

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
        max_pages: int = 50,
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

        all_news = await self._paginated_fetch(
            http_client, url, params, page_param, max_pages, items_per_page, sleep_interval
        )

        catch_up_start_ts = self.get_catch_up_start_ts()
        filtered = [n for n in all_news if n.publish_ts > catch_up_start_ts]

        filtered.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"{self.source.name}补抓完成：共获取{len(filtered)}条历史新闻")

        if filtered:
            self.last_ts = max(n.publish_ts for n in filtered if n.publish_ts > 0)

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
        )

    def _is_newer_than_last(self, ts: int) -> bool:
        """判断时间戳是否比上次更新"""
        return ts > self.last_ts

    def update_last_ts(self, news_list: list[NewsItem]):
        """更新最新时间戳"""
        timestamps = [n.publish_ts for n in news_list if n.publish_ts > 0]
        if timestamps:
            self.last_ts = max(timestamps)
