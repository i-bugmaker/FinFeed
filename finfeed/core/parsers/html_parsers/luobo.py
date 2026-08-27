#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""萝卜投研 解析器"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, ts_from_bj_str

from ..base import BaseParser

logger = logging.getLogger("news_monitor")
class LuoBoParser(BaseParser):
    """萝卜投研 - 通过浏览器渲染捕获网络响应获取数据"""

    SOURCE_URLS = [
        "https://robo.datayes.com/",
    ]

    @staticmethod
    async def _fetch_with_browser(url: str, headers: dict) -> list:
        """使用浏览器渲染并捕获API响应数据"""
        try:
            from playwright.async_api import async_playwright

            all_data = []

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox"]
                )
                page = await browser.new_page(
                    user_agent=headers.get("User-Agent", ""),
                    viewport={"width": 1920, "height": 1080}
                )

                async def handle_response(response):
                    resp_url = response.url
                    if 'gw.datayes.com/rrp_mammon/web/feed/list' in resp_url:
                        try:
                            json_data = await response.json()
                            if json_data.get("code") == 1 and json_data.get("data"):
                                all_data.append(json_data)
                        except Exception as e:
                            logger.debug(f"萝卜投研响应解析失败: {e}")

                page.on('response', handle_response)

                await page.goto(url, timeout=60000)
                await page.wait_for_load_state("networkidle", timeout=30000)
                await page.wait_for_timeout(5000)

                await browser.close()

            return all_data
        except Exception as e:
            logger.warning(f"萝卜投研浏览器渲染失败({url}): {str(e)[:80]}")
            return []

    def _parse_feed_item(self, item: dict, bj_tz, seen_urls: set) -> Optional[NewsItem]:
        """解析feed文章数据"""
        if not isinstance(item, dict):
            return None

        feed_id = item.get("id", "")
        if not feed_id:
            return None

        title = (item.get("title", "") or "").strip()
        if not title or len(title) < 4:
            return None

        url = f"https://robo.datayes.com/v2/details/feed/{feed_id}"
        if url in seen_urls:
            return None
        seen_urls.add(url)

        ts = 0
        publish_time = item.get("publishTime", 0)
        if isinstance(publish_time, (int, float)):
            ts_ms = int(publish_time)
            ts = ts_ms // 1000 if ts_ms > 1e12 else ts_ms
        elif isinstance(publish_time, str):
            ts = ts_from_bj_str(publish_time)

        if ts <= 0:
            return None

        pt = bj_str_from_ts(ts)

        if not self._catch_up_mode and ts and ts <= self.last_ts:
            return None

        intro = ""
        content = item.get("shortDocContent", "") or item.get("description", "")
        if content:
            intro = re.sub(r"<[^>]+>", "", str(content)).strip()[:150]

        news = self._make_news(
            title=title[:80],
            url=url,
            publish_ts=ts,
            publish_time=pt,
            intro=intro,
        )
        return news

    def _parse_html_fallback(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        """从HTML页面提取新闻（备用方案）"""
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if not href:
                continue

            if href.startswith("/v2/details/feed/") or href.startswith("v2/details/feed/") or href.startswith("/v2/article/") or href.startswith("v2/article/"):
                article_id = href.replace("/v2/details/feed/", "").replace("v2/details/feed/", "").replace("/v2/article/", "").replace("v2/article/", "").strip()
                if not article_id or not article_id.isdigit():
                    continue
                url = f"https://robo.datayes.com/v2/details/feed/{article_id}"
            elif href.startswith("http") and "robo.datayes.com" in href:
                url = href
                if "/v2/details/feed/" in href:
                    article_id = href.split("/v2/details/feed/")[-1].split("/")[0]
                    url = f"https://robo.datayes.com/v2/details/feed/{article_id}"
                elif "/v2/article/" in href:
                    article_id = href.split("/v2/article/")[-1].split("/")[0]
                    url = f"https://robo.datayes.com/v2/details/feed/{article_id}"
                else:
                    continue
            else:
                continue

            if url in seen_urls:
                continue

            title = link.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            seen_urls.add(url)
            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro="",
            ))

        for h2 in soup.find_all("h2"):
            title = h2.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            link = h2.find_parent("a", href=True)
            if not link:
                continue

            href = link.get("href", "")
            if not href:
                continue

            if href.startswith("/v2/details/feed/") or href.startswith("/v2/article/"):
                article_id = href.replace("/v2/details/feed/", "").replace("/v2/article/", "").strip()
                url = f"https://robo.datayes.com/v2/details/feed/{article_id}"
            elif href.startswith("http") and "robo.datayes.com" in href:
                if "/v2/details/feed/" in href:
                    article_id = href.split("/v2/details/feed/")[-1].split("/")[0]
                    url = f"https://robo.datayes.com/v2/details/feed/{article_id}"
                elif "/v2/article/" in href:
                    article_id = href.split("/v2/article/")[-1].split("/")[0]
                    url = f"https://robo.datayes.com/v2/details/feed/{article_id}"
                else:
                    url = href
            else:
                continue

            if url in seen_urls:
                continue

            seen_urls.add(url)
            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro="",
            ))

        return news_list

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()
        headers = dict(self.source.headers)
        logger.info(f"萝卜投研开始解析，last_ts={self.last_ts}")

        for url in self.SOURCE_URLS:
            try:
                logger.info("萝卜投研浏览器渲染中...")
                data_list = await self._fetch_with_browser(url, headers)
                logger.info(f"萝卜投研浏览器渲染完成，获取到 {len(data_list)} 个API响应")
                for data in data_list:
                    if not isinstance(data, dict):
                        continue
                    feed_data = data.get("data", {})
                    if not isinstance(feed_data, dict):
                        continue
                    items = feed_data.get("list", [])
                    if not isinstance(items, list):
                        continue
                    logger.info(f"萝卜投研解析到 {len(items)} 条原始数据")
                    for item in items:
                        news = self._parse_feed_item(item, bj_tz, seen_urls)
                        if news:
                            news_list.append(news)
            except Exception as e:
                logger.warning(f"萝卜投研浏览器解析失败({url}): {str(e)[:80]}")

        logger.info(f"萝卜投研浏览器解析结果: {len(news_list)} 条")

        if not news_list:
            logger.info("萝卜投研浏览器解析为空，尝试HTML备用方案")
            try:
                html_news = self._parse_html_fallback(response.text, bj_tz, seen_urls)
                logger.info(f"萝卜投研HTML备用方案解析到 {len(html_news)} 条")
                news_list.extend(html_news)
            except Exception as e:
                logger.warning(f"萝卜投研HTML解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"萝卜投研最终解析结果: {len(news_list)} 条")
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：获取萝卜投研数据

        加固(2026-08-24)：补抓模式跳过浏览器渲染（单次渲染 60s 超时 + 常驻
        playwright 驱动，易挂起并拖垮整轮补抓节奏），直接返回空；实时模式
        parse() 仍走浏览器渲染，不受影响。缺失历史数据由实时轮次自然覆盖。
        """
        logger.info(
            f"萝卜投研补抓模式降级跳过（浏览器渲染不参与补抓），last_ts={self.last_ts}"
        )
        return []
