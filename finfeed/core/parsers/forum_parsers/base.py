#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论坛舆情解析器基类"""

import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from abc import abstractmethod

import httpx
from bs4 import BeautifulSoup, Tag

from finfeed.core.parsers.base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.config.settings import get_display_name
from finfeed.utils.time_utils import now_bj, bj_str_from_ts, TZ_BJ
from .utils import (
    extract_stock_from_url, extract_stocks_from_text,
    merge_stocks, find_time_in_element, normalize_url, parse_forum_time,
)

logger = logging.getLogger("news_monitor")


class BrowserManager:
    _instance = None
    _browser = None
    _semaphore = None
    _initialized = False
    _lock = None

    @classmethod
    async def get_instance(cls):
        import asyncio
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        if cls._semaphore is None:
            cls._semaphore = asyncio.Semaphore(1)
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def _init_browser(self):
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright
            p = await async_playwright().__aenter__()
            self._browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                    "--disable-extensions", "--disable-translate", "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ]
            )
            self._initialized = True
            logger.info("浏览器管理器初始化成功")
        except Exception as e:
            logger.error(f"浏览器初始化失败: {str(e)[:100]}")
            self._initialized = False

    async def fetch(self, url: str, headers: dict, timeout: int = 30000) -> str:
        import asyncio
        async with self._semaphore:
            try:
                if not self._initialized:
                    await self._init_browser()
                if not self._browser or not self._initialized:
                    return ""
                page = await self._browser.new_page(user_agent=headers.get("User-Agent", ""))
                await page.set_extra_http_headers(headers)
                try:
                    await page.goto(url, timeout=timeout)
                    await page.wait_for_load_state("networkidle", timeout=min(timeout, 15000))
                    await page.wait_for_timeout(1500)
                    content = await page.content()
                    return content
                finally:
                    await page.close()
            except Exception as e:
                logger.warning(f"浏览器渲染失败({url}): {str(e)[:80]}")
                self._initialized = False
                return ""


async def fetch_with_browser(url: str, headers: dict, timeout: int = 30000) -> str:
    manager = await BrowserManager.get_instance()
    return await manager.fetch(url, headers, timeout)


class BaseForumParser(BaseParser):
    """论坛舆情解析器基类，封装通用解析逻辑"""

    def __init__(self, source):
        super().__init__(source)
        self._base_url = source.url
        self._url_stock = extract_stock_from_url(source.url)
        self._seen_urls = set()

    def _get_stocks_from_source(self) -> list[dict]:
        stocks = []
        if self._url_stock:
            stocks.append(self._url_stock)
        name = self.source.name
        stock_map = [
            ("茅台", "600519", "贵州茅台", "sh"),
            ("宁德", "300750", "宁德时代", "sz"),
            ("比亚迪", "002594", "比亚迪", "sz"),
            ("工商银行", "601398", "工商银行", "sh"),
            ("招商银行", "600036", "招商银行", "sh"),
            ("平安银行", "000001", "平安银行", "sz"),
            ("东方财富", "300059", "东方财富", "sz"),
            ("中际旭创", "300308", "中际旭创", "sz"),
            ("海康", "002415", "海康威视", "sz"),
            ("中信证券", "600030", "中信证券", "sh"),
            ("五粮液", "000858", "五粮液", "sz"),
            ("科大讯飞", "002230", "科大讯飞", "sz"),
            ("恒瑞医药", "600276", "恒瑞医药", "sh"),
            ("中国平安", "601318", "中国平安", "sh"),
            ("中国石油", "601857", "中国石油", "sh"),
            ("长城军工", "601606", "长城军工", "sh"),
            ("通富微电", "002156", "通富微电", "sz"),
        ]
        for kw, code, sname, market in stock_map:
            if kw in name or code in name:
                stocks.append({"code": code, "name": sname, "market": market})
                break
        return stocks

    def _build_news_item(
        self,
        title: str,
        url: str,
        publish_ts: int = 0,
        publish_time: str = "",
        intro: str = "",
        extra_stocks: Optional[List[dict]] = None,
    ) -> Optional[NewsItem]:
        if not title or len(title) < 4:
            return None
        url = normalize_url(url, self._base_url)
        if not url or url in self._seen_urls:
            return None
        self._seen_urls.add(url)
        now_ts = int(now_bj().replace(tzinfo=TZ_BJ).timestamp())
        if publish_ts <= 0 or publish_ts > now_ts + 300:
            publish_ts = now_ts
        if publish_ts < now_ts - 7 * 24 * 3600:
            return None
        if publish_ts <= self.last_ts:
            return None
        if not publish_time:
            publish_time = bj_str_from_ts(publish_ts)
        source_stocks = self._get_stocks_from_source()
        text_stocks = extract_stocks_from_text(f"{title} {intro}")
        all_stocks = source_stocks + (extra_stocks or []) + text_stocks
        news = NewsItem(
            title=title[:100],
            url=url,
            source=get_display_name(self.source.name),
            publish_time=publish_time,
            publish_ts=publish_ts,
            intro=intro[:200] if intro else "",
            stocks=merge_stocks([all_stocks]),
            category="forum",
        )
        return news

    def _is_empty_page(self, html_text: str, min_links: int = 5) -> bool:
        try:
            soup = BeautifulSoup(html_text, "lxml")
            content_tags = soup.find_all("a", href=True)
            return len(content_tags) < min_links
        except Exception:
            return True

    async def _try_browser_render(self) -> str:
        try:
            return await fetch_with_browser(
                self.source.url, dict(self.source.headers), timeout=45000
            )
        except Exception:
            return ""

    @abstractmethod
    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        pass

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []


class BaseHtmlForumParser(BaseForumParser):
    """HTML论坛解析器基类"""

    item_selectors: List[str] = []
    title_selectors: List[str] = ["a"]
    link_selectors: List[str] = ["a[href]"]
    time_selectors: List[str] = [".time", ".date", "[class*='time']", "[class*='date']"]
    intro_selectors: List[str] = ["p", ".content", ".desc", ".summary", "span"]
    min_title_length: int = 4

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        self._seen_urls.clear()
        try:
            html_text = response.text
            if self._is_empty_page(html_text):
                logger.info(f"{self.source.name}页面为空，尝试浏览器渲染")
                browser_html = await self._try_browser_render()
                if browser_html:
                    html_text = browser_html
            news_list = self._parse_html(html_text)
        except Exception as e:
            logger.warning(f"{self.source.name}解析失败: {str(e)[:80]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _parse_html(self, html_text: str) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")
        items = []
        for selector in self.item_selectors:
            try:
                found = soup.select(selector)
                if found and len(found) > 2:
                    items = found
                    break
            except Exception:
                continue
        if not items:
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if text and len(text) >= self.min_title_length and self._is_valid_link(href):
                    items.append(a)
        for item in items:
            try:
                news = self._parse_item(item, soup)
                if news:
                    news_list.append(news)
            except Exception:
                continue
        return news_list

    def _is_valid_link(self, href: str) -> bool:
        return bool(href) and not href.startswith("#") and "javascript:" not in href

    def _parse_item(self, item: Tag, soup: BeautifulSoup) -> Optional[NewsItem]:
        link_elem = item
        if item.name != "a":
            for sel in self.link_selectors:
                try:
                    found = item.select_one(sel)
                    if found and found.get("href"):
                        link_elem = found
                        break
                except Exception:
                    continue
        href = link_elem.get("href", "")
        if not href or not self._is_valid_link(href):
            return None
        title_elem = link_elem
        if item.name != "a":
            for sel in self.title_selectors:
                try:
                    found = item.select_one(sel)
                    if found and found.get_text(strip=True):
                        title_elem = found
                        break
                except Exception:
                    continue
        title = title_elem.get_text(strip=True)
        if not title or len(title) < self.min_title_length:
            return None
        ts = 0
        for sel in self.time_selectors:
            try:
                time_elem = item.select_one(sel)
                if time_elem:
                    time_text = time_elem.get_text(strip=True)
                    time_attr = time_elem.get("title", "") or time_elem.get("data-time", "") or ""
                    ts = parse_forum_time(time_text) or parse_forum_time(time_attr)
                    if ts > 0:
                        break
            except Exception:
                continue
        if ts <= 0:
            ts = find_time_in_element(item)
        intro = ""
        for sel in self.intro_selectors:
            try:
                intro_elem = item.select_one(sel)
                if intro_elem and intro_elem != title_elem:
                    intro_text = intro_elem.get_text(strip=True)
                    if intro_text and intro_text != title:
                        intro = intro_text
                        break
            except Exception:
                continue
        return self._build_news_item(
            title=title,
            url=href,
            publish_ts=ts,
            intro=intro,
        )


class BaseJsonForumParser(BaseForumParser):
    """JSON API论坛解析器基类"""

    data_path: List[str] = ["data", "list"]
    title_key: str = "title"
    url_key: str = "url"
    time_key: str = "ctime"
    intro_key: str = "summary"
    time_is_timestamp: bool = True
    time_format: str = ""
    base_url: str = ""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        self._seen_urls.clear()
        try:
            data = response.json()
            items = data
            for key in self.data_path:
                if isinstance(items, dict):
                    items = items.get(key, [])
                else:
                    break
            if not isinstance(items, list):
                items = []
            news_list = self._parse_items(items)
        except Exception as e:
            logger.warning(f"{self.source.name} JSON解析失败: {str(e)[:80]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _parse_items(self, items: list) -> list[NewsItem]:
        news_list = []
        for item in items:
            try:
                if not isinstance(item, dict):
                    continue
                news = self._parse_single_item(item)
                if news:
                    news_list.append(news)
            except Exception:
                continue
        return news_list

    def _parse_single_item(self, item: dict) -> Optional[NewsItem]:
        title = item.get(self.title_key, "")
        url = item.get(self.url_key, "")
        if not title or not url:
            return None
        ts = self._extract_timestamp(item.get(self.time_key, 0))
        intro = item.get(self.intro_key, "") or ""
        extra_stocks = []
        stocks_field = item.get("stocks", []) or item.get("stock_list", []) or item.get("related_stocks", [])
        if isinstance(stocks_field, list):
            for s in stocks_field:
                if isinstance(s, dict):
                    extra_stocks.append({
                        "code": s.get("code", ""),
                        "name": s.get("name", "") or s.get("stock_name", ""),
                        "market": s.get("market", ""),
                    })
                elif isinstance(s, str) and len(s) == 6:
                    extra_stocks.append({"code": s, "name": "", "market": ""})
        return self._build_news_item(
            title=str(title),
            url=str(url),
            publish_ts=ts,
            intro=str(intro),
            extra_stocks=extra_stocks,
        )

    def _extract_timestamp(self, time_val) -> int:
        if not time_val:
            return 0
        if isinstance(time_val, (int, float)):
            ts = int(time_val)
            if ts > 10000000000:
                ts = ts // 1000
            return ts
        if isinstance(time_val, str):
            ts = parse_forum_time(time_val)
            if ts > 0:
                return ts
            if self.time_format:
                try:
                    dt = datetime.strptime(time_val, self.time_format).replace(tzinfo=TZ_BJ)
                    return int(dt.timestamp())
                except Exception:
                    pass
        return 0
