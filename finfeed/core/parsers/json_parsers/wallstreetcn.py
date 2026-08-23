#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""华尔街见闻 解析器"""

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts

from ..base import BaseParser


class WallStreetCNParser(BaseParser):
    """华尔街见闻 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        for a in data.get("data", {}).get("items", []):
            if a.get("resource_type") in ("theme", "ad"):
                continue
            resource = a.get("resource", {})
            title = (resource.get("title", "") or resource.get("content_short", "")).strip()
            if not title:
                continue
            display_time = resource.get("display_time", 0)
            ts = int(display_time) if display_time else 0
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            url = resource.get("uri", "")
            if url and not url.startswith("http"):
                url = f"https://wallstreetcn.com{url}"
            news_list.append(self._make_news(
                title=title[:80],
                url=url or "#",
                publish_ts=ts,
                publish_time=pt,
                intro=(resource.get("content_short", "") or "")[:150],
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        params = {"channel": "global-channel", "accept": "article", "limit": 30}
        return await self._catch_up_paginated(
            http_client, self.source.url, params,
            page_param="page", max_pages=30, items_per_page=30
        )
