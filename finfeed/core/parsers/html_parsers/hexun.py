#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""和讯网 解析器"""

import re
import logging
from datetime import datetime, timezone, timedelta
import httpx
from bs4 import BeautifulSoup
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, parse_relative_time
from ._shared import _extract_time_from_parent
logger = logging.getLogger("news_monitor")
class HexunParser(BaseParser):
    """和讯网 - HTML 页面（使用浏览器渲染绕过反爬虫）"""

    _RE_HEXUN_URL = re.compile(r"/(\d{4})-(\d{2})-(\d{2})/(\d+)\.html")
    _RE_CLEAN_TITLE = re.compile(r"^[•●■★◆●\s]+|[•●■★◆●\s]+$")
    _RE_OBFUSCATED = re.compile(r"<script>window\._[A-Za-z]+")

    @staticmethod
    def _is_obfuscated(html_text: str) -> bool:
        """检测页面是否被反爬混淆"""
        return bool(HexunParser._RE_OBFUSCATED.search(html_text[:500]))

    @staticmethod
    async def _fetch_with_browser(url: str, headers: dict) -> str:
        """使用浏览器渲染获取页面内容"""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=headers.get("User-Agent", ""))
                await page.goto(url, timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=15000)
                content = await page.content()
                await browser.close()
                return content
        except Exception as e:
            logger.warning(f"和讯网浏览器渲染失败: {str(e)[:80]}")
            return ""

    async def _parse_html(self, html_text: str) -> list[NewsItem]:
        """解析HTML文本提取新闻"""
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")
        bj_tz = timezone(timedelta(hours=8))

        for item in soup.find_all("a"):
            url = item.get("href", "")
            if not url:
                continue

            if url.startswith("//"):
                url = "https:" + url
            elif not url.startswith("http"):
                continue

            if "stock.hexun.com/" not in url and "news.hexun.com/" not in url:
                continue

            m = self._RE_HEXUN_URL.search(url)
            if not m:
                continue

            year, month, day, news_id = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)

            title = item.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            title = self._RE_CLEAN_TITLE.sub("", title)

            if not title or len(title) < 4:
                continue

            if "注册资本" in title or "成立" in title:
                continue

            ts = 0
            time_str = _extract_time_from_parent(item)
            if time_str:
                ts = parse_relative_time(time_str)

            if ts <= 0:
                try:
                    dt = datetime(year, month, day, 0, 0, 0, tzinfo=bj_tz)
                    ts = int(dt.timestamp())
                except ValueError:
                    continue

            pt = bj_str_from_ts(ts)

            # 注意：和讯网发布时间多由 URL 日期 (/YYYY-MM-DD/) 推导，精度仅到"日 00:00"。
            # 若用 <= 比较，一旦 last_ts 到达某日 00:00，当天所有文章(同为 00:00)都会被跳过，
            # 导致时间线停滞在该日。改用 < 仅跳过严格更早的，当日文章由 URL 去重防止重复入库。
            if ts and ts < self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro="",
            ))

        news_list = list({n.url: n for n in news_list}.values())
        return news_list

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        html_text = response.content.decode("gbk", errors="replace")

        if self._is_obfuscated(html_text):
            logger.info("和讯网页面被反爬混淆，尝试浏览器渲染")
            browser_html = await self._fetch_with_browser(
                self.source.url, dict(self.source.headers)
            )
            if browser_html:
                return await self._parse_html(browser_html)
            return []

        return await self._parse_html(html_text)

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：和讯网页面不支持分页，返回空"""
        return []
