#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻解析器基类

策略模式：每个新闻源对应一个 Parser 子类，负责将 HTTP 响应解析为 NewsItem 列表。
"""

import re
from abc import ABC, abstractmethod
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from storage.models import NewsItem
from utils.time_utils import ts_from_bj_str, bj_str_from_ts, now_bj, parse_relative_time
from utils.http_utils import strip_html
from config.sources import NewsSource
from config.settings import get_display_name


class BaseParser(ABC):
    """解析器基类"""

    def __init__(self, source: NewsSource):
        self.source = source
        self.last_ts: int = 0

    @abstractmethod
    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        """解析 HTTP 响应，返回新闻列表"""
        pass

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
