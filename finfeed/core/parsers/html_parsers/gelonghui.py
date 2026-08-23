#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""格隆汇文章 解析器"""

import httpx
from bs4 import BeautifulSoup

from finfeed.config.settings import get_display_name
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, parse_relative_time

from ..base import BaseParser


class GelonghuiArticleParser(BaseParser):
    """格隆汇文章 - HTML 页面"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(response.text, "lxml")
        for article in soup.select(".article-content"):
            link_elem = article.select_one(".detail-right > a")
            if not link_elem:
                continue
            url = link_elem.get("href", "")
            if url and not url.startswith("http"):
                url = f"https://www.gelonghui.com{url}"
            title_elem = link_elem.select_one("h2")
            title = title_elem.get_text(strip=True) if title_elem else ""
            if not title:
                continue
            info_elem = article.select_one(".time > span:nth-child(1)")
            info = info_elem.get_text(strip=True) if info_elem else ""
            time_elem = article.select_one(".time > span:nth-child(3)")
            time_str = time_elem.get_text(strip=True) if time_elem else ""
            ts = parse_relative_time(time_str)
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            news_list.append(self._make_news(
                title=title[:80],
                url=url or "#",
                publish_ts=ts,
                publish_time=pt,
                intro=info[:150] if info else "",
                source_name=get_display_name(self.source.name),
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：格隆汇文章页面不支持分页，返回空"""
        return []
