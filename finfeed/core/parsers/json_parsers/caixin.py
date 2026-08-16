#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""财新网 解析器

使用财新网关 dataplatform 滚动新闻接口：
  GET https://gateway.caixin.com/api/dataplatform/scroll/index
  params: page / size / date(YYYY-MM-DD 可选) / channel(频道ID 可选)
返回 data.articleList，每项含 title / summary / url / time(epoch 毫秒) 等字段。
"""

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts

from ..base import BaseParser


class CaixinParser(BaseParser):
    """财新网滚动新闻 - dataplatform scroll API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        try:
            data = response.json().get("data", {}) or {}
        except ValueError:
            return news_list
        for a in data.get("articleList", []) or []:
            title = (a.get("title") or "").strip()
            if not title:
                continue
            ms = a.get("time") or 0
            ts = int(ms) // 1000 if ms else 0
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            url = (a.get("url") or "").strip() or "#"
            intro = (a.get("summary") or "").strip()
            news_list.append(self._make_news(
                title=title,
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据（每页 50 条，最多 30 页）"""
        params = dict(self.source.params)
        params.setdefault("size", 50)
        return await self._catch_up_paginated(
            http_client, self.source.url, params,
            page_param="page", max_pages=30, items_per_page=50,
        )
