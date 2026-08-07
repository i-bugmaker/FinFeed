#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""格隆汇快讯 解析器"""

import httpx
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts
from finfeed.config.settings import get_display_name
class GelonghuiLiveParser(BaseParser):
    """格隆汇快讯 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        items = data.get("result") or []
        for item in items:
            ts = item.get("createTimestamp", 0)
            if not isinstance(ts, int) or ts <= 0:
                continue
            if ts <= self.last_ts:
                continue
            title = (item.get("title") or "").strip()
            content = (item.get("content") or "").strip()
            if not title and not content:
                continue
            if not title:
                title = content[:80]
            pt = bj_str_from_ts(ts)
            route = item.get("route", "")
            url = f"https://www.gelonghui.com{route}" if route and not route.startswith("http") else (route or "#")
            stocks = item.get("relatedStocks") or []
            intro = ", ".join(s.get("name", "") for s in stocks if s.get("name")) if stocks else ""
            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro[:150],
                source_name=get_display_name(self.source.name),
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        params = dict(self.source.params)
        params["pageSize"] = 50
        return await self._catch_up_paginated(
            http_client, self.source.url, params,
            page_param="pageNo", max_pages=10, items_per_page=50
        )
