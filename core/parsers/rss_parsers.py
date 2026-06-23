#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RSS / Atom 类新闻源解析器"""

from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .base import BaseParser
from storage.models import NewsItem
from utils.time_utils import bj_str_from_ts


class RSSParser(BaseParser):
    """通用 RSS/Atom 解析器"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(response.text, "xml")
        for item in soup.find_all("item"):
            title_tag = item.find("title")
            link_tag = item.find("link")
            pub_date_tag = item.find("pubDate")
            desc_tag = item.find("description")

            title = (title_tag.text if title_tag else "无标题").strip()
            link = link_tag.text if link_tag else "#"
            ts, pt = 0, ""
            pub_date = pub_date_tag.text if pub_date_tag else ""
            try:
                if pub_date:
                    pub_clean = pub_date.strip()
                    if pub_clean.endswith(" GMT"):
                        pub_clean = pub_clean[:-4] + " +0000"
                    for fmt in (
                            "%a, %d %b %Y %H:%M:%S %z",
                            "%a, %d %b %Y %H:%M:%S GMT",
                        ):
                        try:
                            dt = datetime.strptime(pub_clean, fmt)
                            ts = int(dt.timestamp())
                            pt = bj_str_from_ts(ts)
                            break
                        except (ValueError, TypeError):
                            continue
            except (ValueError, TypeError):
                pass
            if ts and ts <= self.last_ts:
                continue
            intro = ""
            if desc_tag and desc_tag.text:
                desc_soup = BeautifulSoup(desc_tag.text, "lxml")
                intro = desc_soup.get_text(strip=True)[:150]
            news_list.append(self._make_news(
                title=title,
                url=link,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
            ))
        return news_list
