#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""九言财经 解析器"""

import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts
logger = logging.getLogger("news_monitor")
class JiuyanParser(BaseParser):
    """韭研公社 - 通过浏览器渲染捕获网络响应获取数据"""

    SOURCE_URLS = [
        "https://www.jiuyangongshe.com/study_publish",
        "https://www.jiuyangongshe.com/study_hot",
        "https://www.jiuyangongshe.com/square_hot",
        "https://www.jiuyangongshe.com/",
    ]

    @staticmethod
    async def _fetch_with_browser(url: str, headers: dict) -> list:
        """使用浏览器渲染并捕获API响应数据"""
        try:
            from playwright.async_api import async_playwright

            all_data = []

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=headers.get("User-Agent", ""))

                async def handle_response(response):
                    resp_url = response.url
                    # 站点 API 主机已由 app.jiuyangongshe.com 迁移至 web-api.jiuyangongshe.com，
                    # 同时兼容两种以避免拦截失效（拦截不到则解析为空，导致数据停滞）。
                    if ('web-api.jiuyangongshe.com' in resp_url or 'app.jiuyangongshe.com' in resp_url) and ('/timeline/news' in resp_url or '/article/announcement' in resp_url):
                        try:
                            json_data = await response.json()
                            if 'data' in json_data and isinstance(json_data['data'], list) and len(json_data['data']) > 0:
                                all_data.append(json_data)
                        except Exception as e:
                            logger.debug(f"九言公社响应解析失败: {e}")

                page.on('response', handle_response)

                await page.goto(url, timeout=45000)
                await page.wait_for_load_state("networkidle", timeout=20000)
                await page.wait_for_timeout(3000)

                await browser.close()

            return all_data
        except Exception as e:
            logger.warning(f"韭研公社浏览器渲染失败({url}): {str(e)[:80]}")
            return []

    def _parse_timeline_item(self, item: dict, bj_tz, seen_urls: set) -> Optional[NewsItem]:
        """解析时间轴文章数据"""
        if not isinstance(item, dict):
            return None

        article_id = item.get("article_id", "")
        if not article_id:
            return None

        title = (item.get("title", "") or "").strip()
        if not title or len(title) < 4:
            return None

        url = f"https://www.jiuyangongshe.com/a/{article_id}"
        if url in seen_urls:
            return None
        seen_urls.add(url)

        ts = 0
        timeline = item.get("timeline", {})
        create_time = timeline.get("create_time", "") or item.get("create_time", "")
        if create_time:
            try:
                dt = datetime.strptime(create_time, "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=bj_tz)
                ts = int(dt.timestamp())
            except ValueError:
                pass

        if ts <= 0:
            return None

        pt = bj_str_from_ts(ts)

        if not self._catch_up_mode and ts and ts <= self.last_ts:
            return None

        intro = ""
        content = item.get("content", "")
        if content:
            intro = re.sub(r"<[^>]+>", "", str(content)).strip()[:150]

        return self._make_news(
            title=title[:80],
            url=url,
            publish_ts=ts,
            publish_time=pt,
            intro=intro,
        )

    def _parse_announcement_item(self, item: dict, bj_tz, seen_urls: set) -> Optional[NewsItem]:
        """解析公告文章数据"""
        if not isinstance(item, dict):
            return None

        article_id = item.get("article_id", "")
        if not article_id:
            return None

        title = (item.get("title", "") or "").strip()
        if not title or len(title) < 4:
            return None

        url = f"https://www.jiuyangongshe.com/a/{article_id}"
        if url in seen_urls:
            return None
        seen_urls.add(url)

        ts = int(datetime.now(bj_tz).timestamp())
        pt = bj_str_from_ts(ts)

        return self._make_news(
            title=title[:80],
            url=url,
            publish_ts=ts,
            publish_time=pt,
            intro="",
        )

    async def _extract_news_from_data(self, data_list: list, bj_tz, seen_urls: set) -> list:
        """从API响应数据中提取新闻"""
        news_list = []
        for data in data_list:
            if not isinstance(data, dict) or "data" not in data:
                continue

            api_data = data["data"]

            if isinstance(api_data, list) and len(api_data) > 0:
                first_item = api_data[0]
                if isinstance(first_item, dict):
                    if "date" in first_item and "list" in first_item:
                        for date_item in api_data:
                            if isinstance(date_item, dict):
                                article_list = date_item.get("list", [])
                                for item in article_list:
                                    news = self._parse_timeline_item(item, bj_tz, seen_urls)
                                    if news:
                                        news_list.append(news)
                    elif "article_id" in first_item:
                        for item in api_data:
                            news = self._parse_announcement_item(item, bj_tz, seen_urls)
                            if news:
                                news_list.append(news)
                    else:
                        for item in api_data:
                            news = self._parse_timeline_item(item, bj_tz, seen_urls)
                            if not news:
                                news = self._parse_announcement_item(item, bj_tz, seen_urls)
                            if news:
                                news_list.append(news)

        return news_list

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()
        headers = dict(self.source.headers)

        for url in self.SOURCE_URLS:
            try:
                data_list = await self._fetch_with_browser(url, headers)
                url_news = await self._extract_news_from_data(data_list, bj_tz, seen_urls)
                news_list.extend(url_news)
            except Exception as e:
                logger.warning(f"韭研公社解析失败({url}): {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：获取韭研公社多个板块的数据"""
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()
        headers = dict(self.source.headers)

        for url in self.SOURCE_URLS:
            try:
                data_list = await self._fetch_with_browser(url, headers)
                url_news = await self._extract_news_from_data(data_list, bj_tz, seen_urls)
                news_list.extend(url_news)
            except Exception as e:
                logger.warning(f"韭研公社补抓失败({url}): {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        if news_list:
            self.last_ts = max(n.publish_ts for n in news_list if n.publish_ts > 0)

        return news_list
