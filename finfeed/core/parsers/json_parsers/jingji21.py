#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""21财经 解析器"""

import re
import httpx
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import ts_from_bj_str, bj_str_from_ts
class Jingji21Parser(BaseParser):
    """21经济网 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        for item in data.get("list", []):
            title = (item.get("title") or "").strip()
            if not title:
                continue
            time_str = item.get("inputtime", "") or ""
            if time_str and len(time_str) == 16:
                time_str += ":00"
            ts = ts_from_bj_str(time_str)
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            url = item.get("url", "") or "#"
            intro = re.sub(r"\s+", " ", (item.get("content") or "").strip())[:150]
            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        params = dict(self.source.params)
        return await self._catch_up_paginated(
            http_client, self.source.url, params,
            page_param="page", max_pages=10, items_per_page=20
        )
