#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企查查 解析器"""

import re
import httpx
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts
from finfeed.utils.http_utils import strip_html
class QCCParser(BaseParser):
    """企查查 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        _RE_QCC_ID = re.compile(r'[?&]id=([a-f0-9]+)')
        data = response.json()
        if not isinstance(data, list):
            data = []
        for item in data:
            ts_ms = item.get("publish_time", 0)
            ts = ts_ms // 1000 if ts_ms > 1e12 else (int(ts_ms) if ts_ms else 0)
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            fd = item.get("feed_data") or {}
            links = fd.get("links") or []
            title = links[0].get("title", "").strip() if links else ""
            if not title:
                title = strip_html(fd.get("content", "")).strip()[:60]
            if not title:
                continue
            news_id = item.get("news_id", "")
            if not news_id and links:
                m = _RE_QCC_ID.search(links[0].get("url", ""))
                news_id = m.group(1) if m else ""
            url = f"https://news.qcc.com/postnews/{news_id}.html?pageSource=dynamic" if news_id else (links[0].get("url", "#") if links else "#")
            intro = strip_html(fd.get("content", "")).strip()
            intro = re.sub(r"\s+", " ", intro)[:150]
            news_list.append(self._make_news(
                title=title[:80],
                url=url or "#",
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        params = dict(self.source.params)
        params["pageSize"] = 50
        return await self._catch_up_paginated(
            http_client, self.source.url, params,
            page_param="firstRankIndex", max_pages=30, items_per_page=50
        )
