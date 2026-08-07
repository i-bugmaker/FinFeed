#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新浪财经 解析器"""

import httpx
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts
class SinaParser(BaseParser):
    """新浪财经 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        for a in data.get("result", {}).get("data", []):
            ctime = a.get("ctime", "")
            ts = int(ctime) if ctime and str(ctime).isdigit() else 0
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            news_list.append(self._make_news(
                title=(a.get("title") or "无标题").strip(),
                url=a.get("url", "#"),
                publish_ts=ts,
                publish_time=pt,
                intro=(a.get("intro", "") or "")[:150],
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []
        params = {"pageid": "153", "lid": "2509", "num": "50"}
        return await self._catch_up_paginated(
            http_client, self.source.url.split("?")[0], params,
            page_param="page", max_pages=10, items_per_page=50
        )
