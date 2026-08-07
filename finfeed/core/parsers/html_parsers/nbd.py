#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每经网 解析器"""

import re
from datetime import datetime, timezone, timedelta
import httpx
from bs4 import BeautifulSoup
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, now_bj
class NBDParser(BaseParser):
    """每经网 - HTML 页面"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(response.text, "lxml")
        today_str = now_bj().strftime("%Y-%m-%d")
        bj_tz = timezone(timedelta(hours=8))

        for item in soup.select("li"):
            time_elem = item.select_one(".li-title .title-p span")
            title_elem = item.select_one(".li-text h1")
            content_link = item.select_one(".li-text a.item_content")
            content_elem = item.select_one(".li-text a.item_content p")

            if not time_elem or not title_elem or not content_link:
                continue

            time_str = time_elem.get_text(strip=True)
            title = title_elem.get_text(strip=True)
            url = content_link.get("href", "#")
            content = content_elem.get_text(strip=True) if content_elem else ""

            if not title or len(title) < 4:
                continue

            try:
                if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", time_str):
                    dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    dt = dt.replace(tzinfo=bj_tz)
                    ts = int(dt.timestamp())
                    pt = bj_str_from_ts(ts)
                elif re.match(r"\d{2}:\d{2}:\d{2}", time_str):
                    dt = datetime.strptime(f"{today_str} {time_str}", "%Y-%m-%d %H:%M:%S")
                    dt = dt.replace(tzinfo=bj_tz)
                    ts = int(dt.timestamp())
                    now_ts = int(datetime.now(bj_tz).timestamp())
                    if ts > now_ts + 60:
                        dt = dt - timedelta(days=1)
                        ts = int(dt.timestamp())
                    pt = bj_str_from_ts(ts)
                else:
                    continue
            except ValueError:
                continue

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=content[:150],
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：每经网只显示当天数据，返回空"""
        return []
