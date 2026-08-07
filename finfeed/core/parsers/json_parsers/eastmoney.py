#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东方财富 解析器"""

import httpx
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import ts_from_bj_str
class EastMoneyParser(BaseParser):
    """东方财富 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        data_section = data.get("data") or {}
        for a in data_section.get("fastNewsList", []) or []:
            st = a.get("showTime", "")
            ts = ts_from_bj_str(st)
            if ts and ts <= self.last_ts:
                continue
            pt = st[:19] if st else ""
            code = a.get("code", "")
            url = f"https://finance.eastmoney.com/a/{code}.html" if code else "#"
            news_list.append(self._make_news(
                title=(a.get("title") or "无标题").strip(),
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=(a.get("summary", "") or "")[:150],
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：东方财富API不支持分页，尝试获取当前数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        try:
            resp = await http_client.get(
                self.source.url,
                headers=dict(self.source.headers),
                params=dict(self.source.params)
            )

            if resp.status_code != 200:
                return []

            news_list = await self.parse(resp)
            catch_up_start_ts = self.get_catch_up_start_ts()
            filtered = [n for n in news_list if n.publish_ts > catch_up_start_ts]

            if filtered:
                self.last_ts = max(n.publish_ts for n in filtered if n.publish_ts > 0)

            return filtered

        except Exception:
            return []
