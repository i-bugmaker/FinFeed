#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""澎湃新闻 解析器"""

import re

import httpx
from bs4 import BeautifulSoup

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, parse_relative_time

from ..base import BaseParser


class ThePaperParser(BaseParser):
    """澎湃新闻 - HTML 页面"""

    _RE_THEPAPER_URL = re.compile(r"/newsDetail_forward_(\d+)")

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(response.text, "lxml")

        news_items = {}

        for t_elem in soup.find_all(["p", "span", "div"], class_=lambda x: x and "author_time" in str(x).lower()):
            time_text = t_elem.get_text(strip=True)
            ts = parse_relative_time(time_text)
            if ts <= 0:
                continue

            container = t_elem
            link_elem = None
            for _ in range(6):
                if container is None:
                    break
                if container.name == "a" and container.get("href"):
                    href = container.get("href", "")
                    if "newsDetail_forward_" in href:
                        link_elem = container
                        break
                for link in container.find_all("a", href=True):
                    href = link.get("href", "")
                    if "newsDetail_forward_" in href:
                        title_text = link.get_text(strip=True)
                        if title_text and len(title_text) >= 4:
                            link_elem = link
                            break
                if link_elem:
                    break
                container = container.parent

            if not link_elem:
                continue

            url = link_elem.get("href", "")
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.thepaper.cn" + url

            if url not in news_items:
                title = link_elem.get_text(strip=True)
                title = re.sub(r"^推荐", "", title).strip()
                title = re.sub(r"^\d{1,2}:\d{2}\s*", "", title).strip()
                if title and len(title) >= 4:
                    news_items[url] = (title, ts)

        for url, (title, ts) in news_items.items():
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

        seen_urls = {n.url for n in news_list}
        for item in soup.find_all("a"):
            url = item.get("href", "")
            if not url:
                continue

            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.thepaper.cn" + url
            elif not url.startswith("http"):
                continue

            if "thepaper.cn/newsDetail_forward_" not in url:
                continue
            if url in seen_urls:
                continue

            title = item.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            title = re.sub(r"^推荐", "", title).strip()
            title = re.sub(r"^\d{1,2}:\d{2}\s*", "", title).strip()
            if not title:
                continue

            ts = 0
            container = item
            for _ in range(5):
                if container is None:
                    break
                for elem in container.find_all(["p", "span", "div"]):
                    text = elem.get_text(strip=True)
                    if text:
                        t_ts = parse_relative_time(text)
                        if t_ts > 0:
                            ts = t_ts
                            break
                if ts > 0:
                    break
                container = container.parent

            if ts <= 0:
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
        """补抓模式：澎湃新闻页面不支持分页，返回空"""
        return []
