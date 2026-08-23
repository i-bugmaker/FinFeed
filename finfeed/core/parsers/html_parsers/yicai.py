#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第一财经 解析器"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts

from ..base import BaseParser

logger = logging.getLogger("news_monitor")
class YicaiParser(BaseParser):
    """第一财经 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))

        try:
            data = response.json()
        except (json.JSONDecodeError, TypeError):
            return news_list

        if not isinstance(data, list):
            return news_list

        seen_urls = set()

        for item in data:
            if not isinstance(item, dict):
                continue

            title = (item.get("NewsTitle") or "").strip()
            if not title or len(title) < 4:
                continue

            url = item.get("url", "")
            if url.startswith("/"):
                url = "https://www.yicai.com" + url
            elif not url.startswith("http"):
                url = "#"

            if url in seen_urls:
                continue
            seen_urls.add(url)

            ts = 0
            create_date = item.get("CreateDate", "")
            if create_date:
                try:
                    if "T" in create_date:
                        dt = datetime.strptime(create_date, "%Y-%m-%dT%H:%M:%S")
                    else:
                        dt = datetime.strptime(create_date, "%Y-%m-%d %H:%M:%S")
                    dt = dt.replace(tzinfo=bj_tz)
                    ts = int(dt.timestamp())
                except ValueError:
                    pass

            if ts <= 0:
                datekey = item.get("datekey", "")
                hm = item.get("hm", "")
                if datekey and hm:
                    try:
                        date_str = datekey.replace(".", "-")
                        dt = datetime.strptime(f"{date_str} {hm}", "%Y-%m-%d %H:%M")
                        dt = dt.replace(tzinfo=bj_tz)
                        ts = int(dt.timestamp())
                    except ValueError:
                        pass

            if ts <= 0:
                continue

            pt = bj_str_from_ts(ts)

            if ts and ts <= self.last_ts:
                continue

            intro = ""
            content = item.get("LiveContent", "")
            if content:
                intro = re.sub(r"<[^>]+>", "", content).strip()[:150]

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
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        logger.info("第一财经补抓模式：开始分页补抓")

        all_news = await self._paginated_fetch(
            http_client,
            "https://www.yicai.com/api/ajax/getbrieflist",
            {"page": 1, "pagesize": 50, "id": 0},
            page_param="page",
            max_pages=10,
            items_per_page=50
        )

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"第一财经补抓完成：共获取{len(all_news)}条历史新闻")

        return all_news
