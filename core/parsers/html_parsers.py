#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML 页面类新闻源解析器"""

import re

import httpx
from bs4 import BeautifulSoup

from .base import BaseParser
from storage.models import NewsItem
from utils.time_utils import (
    ts_from_bj_str, bj_str_from_ts, now_bj,
    parse_relative_time,
)
from config.settings import get_display_name


class XueqiuParser(BaseParser):
    """雪球 - HTML 页面"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        _RE_DATE_PREFIX = re.compile(r"\d{4}-\d{2}-\d{2}")
        soup = BeautifulSoup(response.text, "lxml")
        articles = soup.select(".timeline__item, .status-item, [class*='timeline'] li, [class*='status'] li")
        if not articles:
            articles = soup.find_all("li")
        for article in articles:
            content_elem = article.select_one(".content, [class*='content'], p")
            time_elem = article.select_one(".time, [class*='time'], [class*='date']")
            title_elem = article.select_one(".title, [class*='title']")
            if not content_elem:
                continue
            content = content_elem.get_text(strip=True)[:80]
            if len(content) < 4:
                continue
            ts, pt = 0, ""
            if time_elem:
                time_text = time_elem.get_text(strip=True)
                if time_text and _RE_DATE_PREFIX.match(time_text):
                    try:
                        from datetime import datetime, timezone
                        dt = datetime.strptime(time_text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        ts = int(dt.timestamp())
                        pt = bj_str_from_ts(ts)
                    except ValueError:
                        pass
            if ts and ts <= self.last_ts:
                continue
            link = "#"
            a_tag = article.find("a", href=True)
            if a_tag:
                link = a_tag["href"]
                if not link.startswith("http"):
                    link = f"https://xueqiu.com{link}"
            title = title_elem.get_text(strip=True) if title_elem else content[:60]
            news_list.append(self._make_news(
                title=title[:80],
                url=link,
                publish_ts=ts,
                publish_time=pt,
                intro=content[:150],
            ))
        return news_list


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


class FastbullParser(BaseParser):
    """法布财经 - HTML 页面"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(response.text, "lxml")
        _fb_seen = set()
        for article in soup.select(".news-list"):
            title_elem = article.select_one(".title_name")
            if not title_elem:
                continue
            title_raw = title_elem.get_text(strip=True)
            m = re.search(r"【([^】]+)】", title_raw)
            title = m.group(1).strip() if m else title_raw
            if len(title) < 4:
                continue
            if title in _fb_seen:
                continue
            _fb_seen.add(title)
            date_attr = article.get("data-date", "")
            ts = int(date_attr) // 1000 if date_attr.isdigit() else 0
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            news_list.append(self._make_news(
                title=title[:80],
                url="#",
                publish_ts=ts,
                publish_time=pt,
                intro="",
            ))
        return news_list
