#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中证网 解析器"""

import re
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
import httpx
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, now_bj
from finfeed.config.settings import get_display_name
logger = logging.getLogger("news_monitor")
class ZhongzhengParser(BaseParser):
    """中证快讯 - JS数据文件（按日期存储，支持7天补抓）"""

    CS_BASE_URL = "https://www.cs.com.cn"
    CS_SUB_ID = "2245"

    def _extract_cache_time(self, html_text: str) -> str:
        """从HTML页面提取缓存时间戳"""
        m = re.search(r'tmpCachedDatetime\s*=\s*["\'](\d+)["\']', html_text)
        if m:
            return m.group(1)
        return now_bj().strftime("%Y%m%d%H%M%S")

    def _parse_js_data(self, js_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        """解析JS数据文件中的MI4_PAGE_ARTICLE数组"""
        news_list = []
        
        m = re.search(r'var\s+MI4_PAGE_ARTICLE\s*=\s*(\[.*\])', js_text, re.DOTALL)
        if not m:
            return news_list

        try:
            items = json.loads(m.group(1))
        except (json.JSONDecodeError, TypeError):
            return news_list

        if not isinstance(items, list):
            return news_list

        for item in items:
            if not isinstance(item, dict):
                continue

            if item.get("isTop") == 1:
                continue

            title = (item.get("title") or "").strip()
            if not title or len(title) < 4:
                continue

            url = item.get("external_link") or item.get("url") or ""
            if not url:
                continue
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = self.CS_BASE_URL + url
            elif not url.startswith("http"):
                continue

            if "cs.com.cn" not in url or url in seen_urls:
                continue
            seen_urls.add(url)

            pub_date = item.get("pub_date", "")
            ts = 0
            pt = ""
            if pub_date:
                try:
                    if re.match(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", pub_date):
                        dt = datetime.strptime(pub_date, "%Y-%m-%d %H:%M")
                        dt = dt.replace(tzinfo=bj_tz)
                        ts = int(dt.timestamp())
                        pt = bj_str_from_ts(ts)
                except ValueError:
                    pass

            if ts <= 0:
                continue

            if not self._catch_up_mode and ts and ts <= self.last_ts:
                continue

            intro = (item.get("miSummary") or "").strip()

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro[:150] if intro else "",
                source_name=get_display_name(self.source.name),
            ))

        return news_list

    async def _fetch_date_data(self, http_client, date_str: str, cache_time: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        """获取指定日期的数据文件"""
        url = f"{self.CS_BASE_URL}/js/{self.CS_SUB_ID}/mi4_sub_articles_{date_str}.js?v={cache_time}"
        try:
            response = await http_client.get(url, headers=dict(self.source.headers))
            if response.status_code == 200 and len(response.content) > 100:
                js_text = response.text
                return self._parse_js_data(js_text, bj_tz, seen_urls)
        except Exception as e:
            logger.debug(f"中证快讯获取{date_str}数据失败: {e}")
        return []

    def _get_http_client(self, response: httpx.Response) -> httpx.AsyncClient:
        """从response获取http_client，如果没有则创建新的"""
        client = getattr(response, 'client', None)
        if client is not None:
            return client
        return httpx.AsyncClient(
            follow_redirects=True,
            timeout=self.source.timeout or 10.0,
            verify=self.source.verify_ssl,
            headers=dict(self.source.headers),
        )

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text
        except Exception:
            html_text = ""

        cache_time = self._extract_cache_time(html_text)

        http_client = self._get_http_client(response)
        own_client = http_client is not getattr(response, 'client', None)

        try:
            now = now_bj()
            days_to_fetch = 3 if not self._catch_up_mode else 1

            for days_back in range(0, days_to_fetch):
                date = now - timedelta(days=days_back)
                date_str = date.strftime("%Y%m%d")
                day_news = await self._fetch_date_data(http_client, date_str, cache_time, bj_tz, seen_urls)
                news_list.extend(day_news)
        finally:
            if own_client:
                await http_client.aclose()

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：获取最近7天的数据"""
        if not self._catch_up_mode:
            return []

        logger.info(f"中证快讯补抓模式：开始补抓最近7天数据")
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        cache_time = now_bj().strftime("%Y%m%d%H%M%S")
        now = now_bj()

        for days_back in range(0, 8):
            date = now - timedelta(days=days_back)
            date_str = date.strftime("%Y%m%d")
            day_news = await self._fetch_date_data(http_client, date_str, cache_time, bj_tz, seen_urls)
            news_list.extend(day_news)
            logger.debug(f"中证快讯补抓 {date_str}: 获取到{len(day_news)}条")
            await asyncio.sleep(0.3)

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"中证快讯补抓完成：共获取{len(news_list)}条新闻")

        if news_list:
            self.last_ts = max(n.publish_ts for n in news_list if n.publish_ts > 0)

        return news_list
