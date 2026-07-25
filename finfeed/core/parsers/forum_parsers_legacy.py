#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论坛舆情解析器

专门用于解析股票论坛、财经社区的帖子和评论数据。
"""

import re
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from .base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import (
    ts_from_bj_str, bj_str_from_ts, now_bj,
    parse_relative_time,
)
from finfeed.config.settings import get_display_name

logger = logging.getLogger("news_monitor")


class BrowserManager:
    """全局浏览器管理器 - 单例模式，控制并发访问"""
    
    _instance = None
    _browser = None
    _semaphore = asyncio.Semaphore(1)
    _initialized = False
    _lock = asyncio.Lock()
    
    @classmethod
    async def get_instance(cls):
        """获取浏览器管理器实例"""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    async def _init_browser(self):
        """初始化浏览器实例"""
        if self._browser is not None:
            return
        
        try:
            from playwright.async_api import async_playwright
            p = await async_playwright().__aenter__()
            self._browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                    "--disable-translate",
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                ]
            )
            self._initialized = True
            logger.info("浏览器管理器初始化成功")
        except Exception as e:
            logger.error(f"浏览器初始化失败: {str(e)[:100]}")
            self._initialized = False
    
    async def fetch(self, url: str, headers: dict, timeout: int = 30000) -> str:
        """使用浏览器渲染获取页面内容（带并发控制）"""
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
    """通用浏览器渲染函数（通过管理器调用）"""
    manager = await BrowserManager.get_instance()
    return await manager.fetch(url, headers, timeout)

STOCK_CODE_MAP = {
    "600519": "贵州茅台",
    "300750": "宁德时代",
    "002594": "比亚迪",
    "601398": "工商银行",
    "600036": "招商银行",
    "000001": "平安银行",
    "600396": "金山股份",
}

def _extract_stock_name(source_name: str, url: str) -> list:
    stocks = []
    
    if "茅台" in source_name:
        stocks.append("贵州茅台")
    elif "宁德" in source_name:
        stocks.append("宁德时代")
    elif "比亚迪" in source_name:
        stocks.append("比亚迪")
    elif "工商银行" in source_name:
        stocks.append("工商银行")
    elif "招商银行" in source_name:
        stocks.append("招商银行")
    elif "平安银行" in source_name:
        stocks.append("平安银行")
    
    match = re.search(r"/list,(\d+)\.html", url)
    if match:
        code = match.group(1)
        if code in STOCK_CODE_MAP and STOCK_CODE_MAP[code] not in stocks:
            stocks.append(STOCK_CODE_MAP[code])
    
    return stocks

class EastMoneyForumParser(BaseParser):
    """东方财富股吧 - 帖子/评论"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if self._is_empty_page(html_text):
                
                logger.info(f"东方财富股吧页面为空，尝试浏览器渲染: {self.source.name}")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers), timeout=45000
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"东方财富股吧解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        soup = BeautifulSoup(html_text, "lxml")
        content_tags = soup.find_all("a", href=True)
        return len(content_tags) < 5

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")
        stocks = _extract_stock_name(self.source.name, self.source.url)

        for item in soup.find_all(class_=lambda x: x and ("articleh" in str(x) or "listitem" in str(x) or "stockcode" in str(x))):
            a_tag = item.find("a", href=True)
            if not a_tag:
                continue

            href = a_tag["href"]
            if "/news/" not in href and "/article/" not in href and "/list," not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://guba.eastmoney.com" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["span", "div"], class_=lambda x: x and ("author" not in str(x).lower() and "time" not in str(x).lower()))
            if content_elem:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            news_item = self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            )
            news_item.stocks = stocks
            news_list.append(news_item)

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：东方财富股吧不支持分页，返回空"""
        return []

class XueqiuParser(BaseParser):
    """雪球 - 热门讨论/帖子"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if self._is_empty_page(html_text):
                
                logger.info("雪球页面为空，尝试浏览器渲染")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers)
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"雪球解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        """检测页面是否为空"""
        soup = BeautifulSoup(html_text, "lxml")
        content_tags = soup.find_all("a", href=True)
        valid_links = [a for a in content_tags if "/S/" in a["href"] or "/article/" in a["href"]]
        return len(valid_links) < 3

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/S/" not in href and "/article/" not in href and "/status/" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://xueqiu.com" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            parent = a_tag.parent
            if parent:
                content_elem = parent.find(["p", "span", "div"], class_=lambda x: x and "content" in str(x).lower())
                if content_elem and content_elem != a_tag:
                    intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：雪球不支持分页，返回空"""
        return []

class TaogubaParser(BaseParser):
    """淘股吧 - 帖子/讨论"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if self._is_empty_page(html_text):
                
                logger.info("淘股吧页面为空，尝试浏览器渲染")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers), timeout=45000
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"淘股吧解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        """检测页面是否为空"""
        soup = BeautifulSoup(html_text, "lxml")
        content_tags = soup.find_all("a", href=True)
        valid_links = [a for a in content_tags if "/article/" in a["href"] or "/topic/" in a["href"]]
        return len(valid_links) < 3

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all(class_=lambda x: x and ("article" in str(x).lower() or "thread" in str(x).lower())):
            link_elem = item.find("a", href=True)
            if not link_elem:
                continue

            href = link_elem["href"]
            if "/article/" not in href and "/topic/" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.taoguba.com.cn" + url
            elif not url.startswith("http"):
                url = "https://www.taoguba.com.cn" + href

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = link_elem.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["p", "span", "div"], class_=lambda x: x and ("content" in str(x).lower() or "desc" in str(x).lower()))
            if content_elem:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            ))

        if not news_list:
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "/article/" not in href and "/topic/" not in href:
                    continue

                url = href
                if url.startswith("//"):
                    url = "https:" + url
                elif url.startswith("/"):
                    url = "https://www.taoguba.com.cn" + url

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                title = a_tag.get_text(strip=True)
                if not title or len(title) < 4:
                    continue

                ts = int(datetime.now(bj_tz).timestamp())
                pt = bj_str_from_ts(ts)

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro="",
                    source_name=get_display_name(self.source.name),
                ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：淘股吧不支持分页，返回空"""
        return []

class WeiboParser(BaseParser):
    """微博财经 - 热点话题"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if self._is_empty_page(html_text):
                
                logger.info("微博页面为空，尝试浏览器渲染")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers), timeout=45000
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"微博财经解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        """检测页面是否为空"""
        soup = BeautifulSoup(html_text, "lxml")
        hot_list = soup.find_all(class_=lambda x: x and ("hot" in str(x).lower() or "top" in str(x).lower()))
        return len(hot_list) < 2

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all(class_=lambda x: x and ("rank" in str(x).lower() or "list_item" in str(x).lower())):
            link_elem = item.find("a", href=True)
            if not link_elem:
                continue

            href = link_elem["href"]
            if "/weibo?q=" not in href and "/detail/" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://s.weibo.com" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = link_elem.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["p", "span", "div"], class_=lambda x: x and ("content" in str(x).lower() or "text" in str(x).lower()))
            if content_elem:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            ))

        if not news_list:
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "/weibo?q=" not in href and "/detail/" not in href:
                    continue

                url = href
                if url.startswith("//"):
                    url = "https:" + url
                elif url.startswith("/"):
                    url = "https://s.weibo.com" + url

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                title = a_tag.get_text(strip=True)
                if not title or len(title) < 4:
                    continue

                ts = int(datetime.now(bj_tz).timestamp())
                pt = bj_str_from_ts(ts)

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro="",
                    source_name=get_display_name(self.source.name),
                ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：微博不支持分页，返回空"""
        return []

class ZhihuParser(BaseParser):
    """知乎财经 - 热门回答"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if response.status_code == 403 or self._is_empty_page(html_text):
                
                logger.info("知乎返回403或页面为空，尝试浏览器渲染")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers), timeout=45000
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"知乎财经解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        """检测页面是否为空"""
        soup = BeautifulSoup(html_text, "lxml")
        content_tags = soup.find_all("a", href=True)
        valid_links = [a for a in content_tags if "/question/" in a["href"] or "/answer/" in a["href"]]
        return len(valid_links) < 3

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all(class_=lambda x: x and ("FeedItem" in str(x) or "List-item" in str(x) or "QuestionItem" in str(x))):
            link_elem = item.find("a", href=True)
            if not link_elem:
                continue

            href = link_elem["href"]
            if "/question/" not in href and "/answer/" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.zhihu.com" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = link_elem.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["p", "span", "div"], class_=lambda x: x and ("content" in str(x).lower() or "summary" in str(x).lower()))
            if content_elem:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            ))

        if not news_list:
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "/question/" not in href and "/answer/" not in href:
                    continue

                url = href
                if url.startswith("//"):
                    url = "https:" + url
                elif url.startswith("/"):
                    url = "https://www.zhihu.com" + url

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                title = a_tag.get_text(strip=True)
                if not title or len(title) < 4:
                    continue

                ts = int(datetime.now(bj_tz).timestamp())
                pt = bj_str_from_ts(ts)

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro="",
                    source_name=get_display_name(self.source.name),
                ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：知乎不支持分页，返回空"""
        return []

class HuxiuParser(BaseParser):
    """虎嗅网 - 财经科技文章"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if self._is_empty_page(html_text):
                
                logger.info("虎嗅网页面为空，尝试浏览器渲染")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers), timeout=45000
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"虎嗅网解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        """检测页面是否为空"""
        soup = BeautifulSoup(html_text, "lxml")
        content_tags = soup.find_all("a", href=True)
        valid_links = [a for a in content_tags if "/article/" in a["href"] or "/story/" in a["href"]]
        return len(valid_links) < 3

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all(class_=lambda x: x and ("article" in str(x).lower() or "post" in str(x).lower() or "card" in str(x).lower())):
            link_elem = item.find("a", href=True)
            if not link_elem:
                continue

            href = link_elem["href"]
            if "/article/" not in href and "/story/" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.huxiu.com" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = link_elem.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["p", "span", "div"], class_=lambda x: x and ("content" in str(x).lower() or "desc" in str(x).lower()))
            if content_elem:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            ))

        if not news_list:
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "/article/" not in href and "/story/" not in href:
                    continue

                url = href
                if url.startswith("//"):
                    url = "https:" + url
                elif url.startswith("/"):
                    url = "https://www.huxiu.com" + url

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                title = a_tag.get_text(strip=True)
                if not title or len(title) < 4:
                    continue

                ts = int(datetime.now(bj_tz).timestamp())
                pt = bj_str_from_ts(ts)

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro="",
                    source_name=get_display_name(self.source.name),
                ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：虎嗅网不支持分页，返回空"""
        return []

class Kr36Parser(BaseParser):
    """36氪 - 财经科技资讯"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if self._is_empty_page(html_text):
                
                logger.info("36氪页面为空，尝试浏览器渲染")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers), timeout=45000
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"36氪解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        """检测页面是否为空"""
        soup = BeautifulSoup(html_text, "lxml")
        content_tags = soup.find_all("a", href=True)
        valid_links = [a for a in content_tags if "/p/" in a["href"] or "/article/" in a["href"]]
        return len(valid_links) < 3

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all(class_=lambda x: x and ("article" in str(x).lower() or "post" in str(x).lower() or "item" in str(x).lower())):
            link_elem = item.find("a", href=True)
            if not link_elem:
                continue

            href = link_elem["href"]
            if "/p/" not in href and "/article/" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://36kr.com" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = link_elem.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["p", "span", "div"], class_=lambda x: x and ("content" in str(x).lower() or "desc" in str(x).lower()))
            if content_elem:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            ))

        if not news_list:
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if "/p/" not in href and "/article/" not in href:
                    continue

                url = href
                if url.startswith("//"):
                    url = "https:" + url
                elif url.startswith("/"):
                    url = "https://36kr.com" + url

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                title = a_tag.get_text(strip=True)
                if not title or len(title) < 4:
                    continue

                ts = int(datetime.now(bj_tz).timestamp())
                pt = bj_str_from_ts(ts)

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro="",
                    source_name=get_display_name(self.source.name),
                ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：36氪不支持分页，返回空"""
        return []

class ThsStockBarParser(BaseParser):
    """同花顺股吧 - 帖子/讨论"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if self._is_empty_page(html_text):
                
                logger.info("同花顺股吧页面为空，尝试浏览器渲染")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers), timeout=45000
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"同花顺股吧解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        soup = BeautifulSoup(html_text, "lxml")
        content_tags = soup.find_all("a", href=True)
        valid_links = [a for a in content_tags if "/detail/" in a["href"] or "/article/" in a["href"]]
        return len(valid_links) < 3

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all(class_=lambda x: x and ("article" in str(x).lower() or "post" in str(x).lower() or "item" in str(x).lower())):
            link_elem = item.find("a", href=True)
            if not link_elem:
                continue

            href = link_elem["href"]
            if "/detail/" not in href and "/article/" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://g.10jqka.com.cn" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = link_elem.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["p", "span", "div"], class_=lambda x: x and ("content" in str(x).lower() or "desc" in str(x).lower()))
            if content_elem:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []

class ClsForumParser(BaseParser):
    """财联社API - JSON格式"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            data = response.json()
            items = data.get("data", {}).get("items", [])
            
            for item in items:
                title = item.get("title", "")
                url = item.get("url", "")
                if not title or not url:
                    continue
                
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                if url.startswith("//"):
                    url = "https:" + url
                elif not url.startswith("http"):
                    url = "https://www.cls.cn" + url

                ts = item.get("ctime", 0)
                if ts:
                    if isinstance(ts, str):
                        ts = int(ts)
                else:
                    ts = int(datetime.now(bj_tz).timestamp())
                
                pt = bj_str_from_ts(ts)

                intro = item.get("summary", "")[:150]

                if ts and ts <= self.last_ts:
                    continue

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro=intro,
                    source_name=get_display_name(self.source.name),
                ))

        except Exception as e:
            logger.warning(f"财联社API解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []

class JiemianForumParser(BaseParser):
    """界面新闻API - JSON格式"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            data = response.json()
            items = data.get("data", [])
            
            for item in items:
                title = item.get("title", "")
                url = item.get("url", "")
                if not title or not url:
                    continue
                
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                if not url.startswith("http"):
                    url = "https://www.jiemian.com" + url

                ts = item.get("publish_time", 0)
                if ts:
                    if isinstance(ts, str):
                        ts = int(ts)
                else:
                    ts = int(datetime.now(bj_tz).timestamp())
                
                pt = bj_str_from_ts(ts)

                intro = item.get("summary", "")[:150]

                if ts and ts <= self.last_ts:
                    continue

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro=intro,
                    source_name=get_display_name(self.source.name),
                ))

        except Exception as e:
            logger.warning(f"界面新闻API解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []

class EastMoneyForumJsonParser(BaseParser):
    """东方财富财经API - JSON格式"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            data = response.json()
            items = data.get("data", {}).get("list", [])
            
            for item in items:
                title = item.get("title", "")
                url = item.get("url", "")
                if not title or not url:
                    continue
                
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                if url.startswith("//"):
                    url = "https:" + url

                ts = item.get("publishTime", 0)
                if ts:
                    if isinstance(ts, str):
                        ts = int(ts)
                else:
                    ts = int(datetime.now(bj_tz).timestamp())
                
                pt = bj_str_from_ts(ts)

                intro = item.get("intro", "")[:150]

                if ts and ts <= self.last_ts:
                    continue

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro=intro,
                    source_name=get_display_name(self.source.name),
                ))

        except Exception as e:
            logger.warning(f"东方财富财经API解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []

class SinaForumParser(BaseParser):
    """新浪财经API - JSON格式"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            data = response.json()
            items = data.get("result", {}).get("data", [])
            
            for item in items:
                title = item.get("title", "")
                url = item.get("url", "")
                if not title or not url:
                    continue
                
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                ts = item.get("time", "")
                if ts:
                    try:
                        ts = int(datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=bj_tz).timestamp())
                    except:
                        ts = int(datetime.now(bj_tz).timestamp())
                else:
                    ts = int(datetime.now(bj_tz).timestamp())
                
                pt = bj_str_from_ts(ts)

                intro = item.get("summary", "")[:150]

                if ts and ts <= self.last_ts:
                    continue

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro=intro,
                    source_name=get_display_name(self.source.name),
                ))

        except Exception as e:
            logger.warning(f"新浪财经API解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []

class ThsForumParser(BaseParser):
    """同花顺快讯API - JSON格式"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            data = response.json()
            items = data.get("data", {}).get("list", [])
            
            for item in items:
                title = item.get("title", "")
                url = item.get("url", "")
                if not title or not url:
                    continue
                
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                ts = item.get("publish_time", 0)
                if ts:
                    if isinstance(ts, str):
                        ts = int(ts)
                else:
                    ts = int(datetime.now(bj_tz).timestamp())
                
                pt = bj_str_from_ts(ts)

                intro = item.get("summary", "")[:150]

                if ts and ts <= self.last_ts:
                    continue

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro=intro,
                    source_name=get_display_name(self.source.name),
                ))

        except Exception as e:
            logger.warning(f"同花顺快讯API解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []

class SinaCommentParser(BaseParser):
    """新浪财经评论API - JSON格式"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            data = response.json()
            items = data.get("result", {}).get("data", [])
            
            for item in items:
                title = item.get("title", "")
                url = item.get("url", "")
                if not title or not url:
                    continue
                
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                ts = item.get("time", "")
                if ts:
                    try:
                        ts = int(datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=bj_tz).timestamp())
                    except:
                        ts = int(datetime.now(bj_tz).timestamp())
                else:
                    ts = int(datetime.now(bj_tz).timestamp())
                
                pt = bj_str_from_ts(ts)

                intro = item.get("summary", "")[:150]

                if ts and ts <= self.last_ts:
                    continue

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro=intro,
                    source_name=get_display_name(self.source.name),
                ))

        except Exception as e:
            logger.warning(f"新浪财经评论API解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []

class YicaiForumParser(BaseParser):
    """第一财经API - JSON格式"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            data = response.json()
            items = data.get("data", [])
            
            for item in items:
                title = item.get("title", "")
                url = item.get("url", "")
                if not title or not url:
                    continue
                
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                if not url.startswith("http"):
                    url = "https://www.yicai.com" + url

                ts = item.get("publishTime", 0)
                if ts:
                    if isinstance(ts, str):
                        ts = int(ts)
                else:
                    ts = int(datetime.now(bj_tz).timestamp())
                
                pt = bj_str_from_ts(ts)

                intro = item.get("summary", "")[:150]

                if ts and ts <= self.last_ts:
                    continue

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro=intro,
                    source_name=get_display_name(self.source.name),
                ))

        except Exception as e:
            logger.warning(f"第一财经API解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []

class EgupiaoParser(BaseParser):
    """股吧热门 - egupiao.com"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if self._is_empty_page(html_text):
                
                logger.info("股吧热门页面为空，尝试浏览器渲染")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers), timeout=45000
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"股吧热门解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        soup = BeautifulSoup(html_text, "lxml")
        content_tags = soup.find_all("a", href=True)
        valid_links = [a for a in content_tags if "/article/" in a["href"] or "/post/" in a["href"] or "/thread/" in a["href"]]
        return len(valid_links) < 3

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all(class_=lambda x: x and ("article" in str(x).lower() or "post" in str(x).lower() or "thread" in str(x).lower())):
            link_elem = item.find("a", href=True)
            if not link_elem:
                continue

            href = link_elem["href"]
            if "/article/" not in href and "/post/" not in href and "/thread/" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.egupiao.com" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = link_elem.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["p", "span", "div"], class_=lambda x: x and ("content" in str(x).lower() or "desc" in str(x).lower()))
            if content_elem:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []

class GupiaoluntanParser(BaseParser):
    """股吧论坛 - gupiaoluntan.com"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if self._is_empty_page(html_text):
                
                logger.info("股吧论坛页面为空，尝试浏览器渲染")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers), timeout=45000
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"股吧论坛解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        soup = BeautifulSoup(html_text, "lxml")
        content_tags = soup.find_all("a", href=True)
        valid_links = [a for a in content_tags if "/article/" in a["href"] or "/post/" in a["href"] or "/thread/" in a["href"]]
        return len(valid_links) < 3

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all(class_=lambda x: x and ("article" in str(x).lower() or "post" in str(x).lower() or "thread" in str(x).lower())):
            link_elem = item.find("a", href=True)
            if not link_elem:
                continue

            href = link_elem["href"]
            if "/article/" not in href and "/post/" not in href and "/thread/" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.gupiaoluntan.com" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = link_elem.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["p", "span", "div"], class_=lambda x: x and ("content" in str(x).lower() or "desc" in str(x).lower()))
            if content_elem:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []

class StockbbsParser(BaseParser):
    """股票论坛 - stockbbs.com"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if self._is_empty_page(html_text):
                
                logger.info("股票论坛页面为空，尝试浏览器渲染")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers), timeout=45000
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"股票论坛解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        soup = BeautifulSoup(html_text, "lxml")
        content_tags = soup.find_all("a", href=True)
        valid_links = [a for a in content_tags if "/article/" in a["href"] or "/post/" in a["href"] or "/thread/" in a["href"]]
        return len(valid_links) < 3

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all(class_=lambda x: x and ("article" in str(x).lower() or "post" in str(x).lower() or "thread" in str(x).lower())):
            link_elem = item.find("a", href=True)
            if not link_elem:
                continue

            href = link_elem["href"]
            if "/article/" not in href and "/post/" not in href and "/thread/" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.stockbbs.com" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = link_elem.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["p", "span", "div"], class_=lambda x: x and ("content" in str(x).lower() or "desc" in str(x).lower()))
            if content_elem:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []

class GubarParser(BaseParser):
    """股吧网 - 帖子/讨论"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if self._is_empty_page(html_text):
                
                logger.info("股吧网页面为空，尝试浏览器渲染")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers), timeout=45000
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"股吧网解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        soup = BeautifulSoup(html_text, "lxml")
        content_tags = soup.find_all("a", href=True)
        valid_links = [a for a in content_tags if "/article/" in a["href"] or "/topic/" in a["href"]]
        return len(valid_links) < 3

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all(class_=lambda x: x and ("article" in str(x).lower() or "thread" in str(x).lower() or "post" in str(x).lower())):
            link_elem = item.find("a", href=True)
            if not link_elem:
                continue

            href = link_elem["href"]
            if "/article/" not in href and "/topic/" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.gubar.com" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = link_elem.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["p", "span", "div"], class_=lambda x: x and ("content" in str(x).lower() or "desc" in str(x).lower()))
            if content_elem:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []

class StockstarParser(BaseParser):
    """证券之星 - 股吧讨论"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if self._is_empty_page(html_text):
                
                logger.info("证券之星页面为空，尝试浏览器渲染")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers), timeout=45000
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"证券之星解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        soup = BeautifulSoup(html_text, "lxml")
        content_tags = soup.find_all("a", href=True)
        valid_links = [a for a in content_tags if "/g/" in a["href"] or "/article/" in a["href"]]
        return len(valid_links) < 3

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all(class_=lambda x: x and ("article" in str(x).lower() or "post" in str(x).lower() or "item" in str(x).lower())):
            link_elem = item.find("a", href=True)
            if not link_elem:
                continue

            href = link_elem["href"]
            if "/g/" not in href and "/article/" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://g.stockstar.com" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = link_elem.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["p", "span", "div"], class_=lambda x: x and ("content" in str(x).lower() or "desc" in str(x).lower()))
            if content_elem:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []

class SinaStockBarParser(BaseParser):
    """新浪股吧 - 帖子/讨论"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text
            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"新浪股吧解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all(["li", "div"], class_=lambda x: x):
            a_tag = item.find("a", href=True)
            if not a_tag:
                continue

            href = a_tag["href"]
            if "thread" not in href and "tid" not in href and "bid" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "http://guba.sina.com.cn" + url
            elif not url.startswith("http"):
                url = "http://guba.sina.com.cn" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["span", "div", "p"])
            if content_elem and content_elem != a_tag:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            stocks = []
            bracket_match = re.search(r"\[(.+?)\]", title)
            if bracket_match:
                stock_name = bracket_match.group(1).strip()
                if stock_name:
                    stocks.append(stock_name)

            news_item = self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            )
            news_item.stocks = stocks
            news_list.append(news_item)

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []


class CLSForumParser(BaseParser):
    """财联社 - 早报/快讯舆情"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            soup = BeautifulSoup(html_text, "lxml")
            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"财联社舆情解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all(["article", "div"], class_=lambda x: x and ("item" in str(x) or "news" in str(x) or "article" in str(x))):
            a_tag = item.find("a", href=True)
            if not a_tag:
                continue

            href = a_tag["href"]
            if "/detail/" not in href:
                continue

            url = href
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.cls.cn" + url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            intro = ""
            content_elem = item.find(["p", "span", "div"], class_=lambda x: x and ("desc" in str(x).lower() or "summary" in str(x).lower() or "brief" in str(x).lower()))
            if content_elem:
                intro = content_elem.get_text(strip=True)[:150]

            if ts and ts <= self.last_ts:
                continue

            stocks = []
            stock_match = re.search(r"(贵州茅台|宁德时代|比亚迪|工商银行|招商银行|平安银行|五粮液|美的集团|格力电器|海尔智家)", title)
            if stock_match:
                stocks.append(stock_match.group(1))

            news_item = self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            )
            news_item.stocks = stocks
            news_list.append(news_item)

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []


class ThsStockBarParser(BaseParser):
    """同花顺投顾平台 - 帖子/讨论"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text

            if self._is_empty_page(html_text):
                
                logger.info(f"同花顺投顾页面为空，尝试浏览器渲染: {self.source.name}")
                browser_html = await fetch_with_browser(
                    self.source.url, dict(self.source.headers), timeout=45000
                )
                if browser_html:
                    html_text = browser_html

            news_list = self._parse_html(html_text, bj_tz, seen_urls)

        except Exception as e:
            logger.warning(f"同花顺投顾解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _is_empty_page(self, html_text: str) -> bool:
        soup = BeautifulSoup(html_text, "lxml")
        content_tags = soup.find_all("a", href=True)
        return len(content_tags) < 5

    def _extract_stock_from_href(self, href: str) -> list:
        stocks = []
        stock_match = re.search(r'stockcode=([^&^]+)', href)
        if stock_match:
            code = stock_match.group(1)
            if code in STOCK_CODE_MAP:
                stocks.append(STOCK_CODE_MAP[code])
            elif code.isdigit() and len(code) >= 6:
                stocks.append(f"股票{code}")
        return stocks

    def _parse_html(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for item in soup.find_all("li", class_=lambda x: x and "feed-item" in str(x)):
            main_div = item.find("div", class_="feed-item-main")
            if not main_div:
                continue

            info_div = main_div.find("div", class_="feed-item-container-info")
            if not info_div:
                continue

            info_text = info_div.get_text(strip=True)
            if not info_text or len(info_text) < 4:
                continue

            links = main_div.find_all("a", href=True)
            if not links:
                continue

            main_url = links[0]["href"]
            if main_url in seen_urls:
                continue
            seen_urls.add(main_url)

            title = info_text[:60]
            intro = info_text[:150]

            stocks = []
            for link in links:
                href = link.get("href", "")
                text = link.get_text(strip=True)
                if text and text not in stocks and len(text) > 1:
                    stocks.append(text)
                stock_from_href = self._extract_stock_from_href(href)
                for s in stock_from_href:
                    if s not in stocks:
                        stocks.append(s)
            
            stocks = [s for s in stocks if not (s.isdigit() and len(s) >= 6)]

            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            if ts and ts <= self.last_ts:
                continue

            news_item = self._make_news(
                title=title,
                url=main_url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
                source_name=get_display_name(self.source.name),
            )
            news_item.stocks = stocks[:3]
            news_list.append(news_item)

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        return []
