#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同花顺 解析器"""

import re

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts

from ..base import BaseParser


class THSParser(BaseParser):
    """同花顺 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        _RE_SHARE_URL = re.compile(r"/share/(\d+)/?")
        for a in data.get("data", {}).get("list", []):
            ctime = a.get("ctime", "")
            ts = int(ctime) if ctime and str(ctime).isdigit() else 0
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            share_url = a.get("shareUrl", "")
            url = "#"
            if share_url and "/share/" in share_url:
                m = _RE_SHARE_URL.search(share_url)
                if m:
                    aid = m.group(1)
                    date_str = bj_str_from_ts(ts)[:10].replace("-", "")
                    url = f"https://news.10jqka.com.cn/{date_str}/c{aid}.shtml"
                else:
                    url = share_url
            elif share_url:
                url = share_url
            news_list.append(self._make_news(
                title=(a.get("title") or "无标题").strip(),
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=(a.get("digest", "") or a.get("short", "") or "")[:150],
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        params = dict(self.source.params)
        return await self._catch_up_paginated(
            http_client, self.source.url, params,
            page_param="page", max_pages=10, items_per_page=20
        )
