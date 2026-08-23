#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股专业投资社区舆情解析器：淘股吧、集思录

淘股吧：A股短线游资/涨停板情绪社区，散户讨论信号强。
集思录：转债/套利/打新低风险投资社区，情绪偏专业、信号独立。

两者页面均有一定 JS 渲染与反爬，保留浏览器渲染兜底（_try_browser_render）。
"""

import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup, Tag

from finfeed.utils.time_utils import TZ_BJ, now_bj

from .base import BaseHtmlForumParser
from .utils import extract_stocks_from_text, find_time_in_element

logger = logging.getLogger("news_monitor")


class TaogubaParser(BaseHtmlForumParser):
    """淘股吧舆情 - https://www.taoguba.com.cn/
    首页聚合短线游资/涨停板社区帖，标题即观点。
    """

    item_selectors = ["li", ".newslist li", "ul.list li"]
    title_selectors = ["a"]
    link_selectors = ["a[href*='/Article/']"]
    time_selectors = []
    intro_selectors = []

    async def parse(self, response: httpx.Response) -> list:
        news_list = []
        self._seen_urls.clear()
        try:
            html_text = response.text
            if not html_text or len(html_text) < 500:
                try:
                    html_text = response.content.decode("utf-8", errors="ignore")
                except Exception:
                    pass
            if self._is_empty_page(html_text, min_links=8):
                logger.info(f"{self.source.name}页面为空，尝试浏览器渲染")
                browser_html = await self._try_browser_render()
                if browser_html:
                    html_text = browser_html
            news_list = self._parse_html(html_text)
        except Exception as e:
            logger.warning(f"{self.source.name}解析失败: {str(e)[:80]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _parse_html(self, html_text: str) -> list:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")
        now_ts = int(now_bj().replace(tzinfo=TZ_BJ).timestamp())
        seen = set()
        for a in soup.find_all("a", href=True):
            try:
                href = a.get("href", "")
                if "/Article/" not in href:
                    continue
                title = re.sub(r"\s+", " ", a.get_text(strip=True)).strip()
                if not title or len(title) < 6:
                    continue
                if title in seen:
                    continue
                seen.add(title)
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = "https://www.taoguba.com.cn" + href
                ts = 0
                if a.parent is not None:
                    ts = find_time_in_element(a.parent)
                if ts <= 0:
                    ts = now_ts - len(seen) * 20
                news = self._build_news_item(
                    title=title,
                    url=href,
                    publish_ts=ts,
                    extra_stocks=extract_stocks_from_text(title),
                )
                if news:
                    news_list.append(news)
                if len(news_list) >= 40:
                    break
            except Exception:
                continue
        return news_list

    def _parse_item(self, item: Tag, soup: BeautifulSoup) -> Optional[object]:
        return None


class JisiluParser(BaseHtmlForumParser):
    """集思录舆情 - https://www.jisilu.cn/home/explore
    转债/套利/打新等低风险投资讨论，情绪偏专业。
    """

    item_selectors = ["div.row", "div.topic-item", "tr"]
    title_selectors = ["a.title", "a"]
    link_selectors = ["a[href*='/topic/']"]
    time_selectors = ["span.time", ".time", "td.time", "[class*='time']"]
    intro_selectors = ["div.summary", ".summary", "td"]

    async def parse(self, response: httpx.Response) -> list:
        news_list = []
        self._seen_urls.clear()
        try:
            html_text = response.text
            if not html_text or len(html_text) < 500:
                try:
                    html_text = response.content.decode("utf-8", errors="ignore")
                except Exception:
                    pass
            if self._is_empty_page(html_text, min_links=8):
                logger.info(f"{self.source.name}页面为空，尝试浏览器渲染")
                browser_html = await self._try_browser_render()
                if browser_html:
                    html_text = browser_html
            news_list = self._parse_html(html_text)
        except Exception as e:
            logger.warning(f"{self.source.name}解析失败: {str(e)[:80]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _parse_html(self, html_text: str) -> list:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")
        now_ts = int(now_bj().replace(tzinfo=TZ_BJ).timestamp())
        seen = set()
        for a in soup.find_all("a", href=True):
            try:
                href = a.get("href", "")
                if "/topic/" not in href:
                    continue
                title = re.sub(r"\s+", " ", a.get_text(strip=True)).strip()
                if not title or len(title) < 4:
                    continue
                if title in seen:
                    continue
                seen.add(title)
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = "https://www.jisilu.cn" + href
                ts = 0
                parent = a.parent
                if parent is not None:
                    ts = find_time_in_element(parent)
                if ts <= 0 and parent is not None:
                    for t_el in parent.select(".time, span.time"):
                        ttxt = t_el.get_text(strip=True)
                        if ttxt:
                            from .utils import parse_forum_time
                            ts = parse_forum_time(ttxt)
                            if ts > 0:
                                break
                if ts <= 0:
                    ts = now_ts - len(seen) * 60
                news = self._build_news_item(
                    title=title,
                    url=href,
                    publish_ts=ts,
                    extra_stocks=extract_stocks_from_text(title),
                )
                if news:
                    news_list.append(news)
                if len(news_list) >= 40:
                    break
            except Exception:
                continue
        return news_list

    def _parse_item(self, item: Tag, soup: BeautifulSoup) -> Optional[object]:
        return None
