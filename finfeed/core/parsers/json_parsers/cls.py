#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""财联社 解析器"""

import re
import logging
import httpx
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts
logger = logging.getLogger("news_monitor")
class CLSParser(BaseParser):
    """财联社电报 - 使用 /api/cache 无签名API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        for a in data.get("data", {}).get("roll_data", []):
            ctime = a.get("ctime", "")
            ts = int(ctime) if ctime and str(ctime).isdigit() else 0
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            title = (a.get("title") or a.get("brief", "") or "").strip()
            content = (a.get("content", "") or a.get("brief", "") or "").strip()
            title = re.sub(r'<[^>]+>', '', title)
            content = re.sub(r'<[^>]+>', '', content)
            if not title and content:
                title = content[:80]
            if not title:
                continue
            url = a.get("shareurl", "") or f"https://www.cls.cn/detail/{a.get('id', '')}"
            news_list.append(self._make_news(
                title=title[:100],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=content[:200],
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：使用api/cache端点获取最新一批数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []
        try:
            resp = await http_client.get(
                self.source.url,
                headers=dict(self.source.headers),
            )
            if resp.status_code == 200:
                news_list = await self.parse(resp)
                if news_list:
                    self.last_ts = max(n.publish_ts for n in news_list if n.publish_ts > 0)
                return news_list
        except Exception as e:
            logger.warning(f"财联社补抓失败：{str(e)[:80]}")
        return []
