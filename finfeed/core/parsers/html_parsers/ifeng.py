#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""凤凰财经 解析器"""

import re

import httpx
from bs4 import BeautifulSoup

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, parse_relative_time

from ..base import BaseParser


class IfengParser(BaseParser):
    """凤凰财经 - HTML 页面"""

    _RE_IFENG_VALID = re.compile(r"ifeng\.com/c/")

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(response.text, "lxml")

        time_elems = soup.find_all(class_=lambda x: x and "newsFeedTime" in str(x))
        seen_urls = set()

        for time_elem in time_elems:
            time_str = time_elem.get_text(strip=True)
            if not time_str:
                continue

            ts = parse_relative_time(time_str)
            if ts <= 0:
                continue

            link_elem = None
            container = time_elem
            for _ in range(5):
                if container is None:
                    break
                if container.name == "a" and container.get("href"):
                    href = container.get("href", "")
                    if self._RE_IFENG_VALID.search(href):
                        link_elem = container
                        break
                container = container.parent

            if not link_elem:
                continue

            url = link_elem.get("href", "")
            if not url:
                continue
            if url.startswith("//"):
                url = "https:" + url
            elif not url.startswith("http"):
                url = "https://finance.ifeng.com" + url
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title_elem = link_elem.find(["h2", "h3", "h4", "p", "span"], class_=lambda x: x and ("title" in str(x).lower() or "name" in str(x).lower()))
            if title_elem:
                title = title_elem.get_text(strip=True)
            else:
                all_text = link_elem.get_text(" ", strip=True)
                title = re.sub(r"\d{2}-\d{2}\s+\d{2}:\d{2}.*$", "", all_text).strip()
                title = re.sub(r"\d+评$", "", title).strip()

            if not title or len(title) < 4:
                continue

            pt = bj_str_from_ts(ts)

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro="",
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：凤凰财经页面不支持分页，返回空"""
        return []
