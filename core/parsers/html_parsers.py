#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML 页面类新闻源解析器"""

import re
import json
from datetime import datetime, timezone, timedelta

import httpx
from bs4 import BeautifulSoup

from .base import BaseParser
from storage.models import NewsItem
from utils.time_utils import (
    ts_from_bj_str, bj_str_from_ts, now_bj,
    parse_relative_time,
)
from config.settings import get_display_name


class GelonghuiArticleParser(BaseParser):
    """格隆汇文章 - HTML 页面"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(response.text, "lxml")
        for article in soup.select(".article-content"):
            link_elem = article.select_one(".detail-right > a")
            if not link_elem:
                continue
            url = link_elem.get("href", "")
            if url and not url.startswith("http"):
                url = f"https://www.gelonghui.com{url}"
            title_elem = link_elem.select_one("h2")
            title = title_elem.get_text(strip=True) if title_elem else ""
            if not title:
                continue
            info_elem = article.select_one(".time > span:nth-child(1)")
            info = info_elem.get_text(strip=True) if info_elem else ""
            time_elem = article.select_one(".time > span:nth-child(3)")
            time_str = time_elem.get_text(strip=True) if time_elem else ""
            ts = parse_relative_time(time_str)
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            news_list.append(self._make_news(
                title=title[:80],
                url=url or "#",
                publish_ts=ts,
                publish_time=pt,
                intro=info[:150] if info else "",
                source_name=get_display_name(self.source.name),
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：格隆汇文章页面不支持分页，返回空"""
        return []


class FastbullParser(BaseParser):
    """法布财经 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()

        if data.get("code") != 0:
            return news_list

        body_raw = data.get("bodyMessage")
        if not body_raw:
            return news_list

        if isinstance(body_raw, str):
            try:
                body = json.loads(body_raw)
            except (json.JSONDecodeError, TypeError):
                return news_list
        else:
            body = body_raw

        items = body.get("pageDatas") or []
        for item in items:
            if not isinstance(item, dict):
                continue

            title = (item.get("newsTitle") or "").strip()
            if not title or len(title) < 4:
                continue

            released = item.get("releasedDate") or 0
            if isinstance(released, (int, float)):
                ts_ms = int(released)
                ts = ts_ms // 1000 if ts_ms > 1e12 else ts_ms
            else:
                ts = ts_from_bj_str(str(released)) if released else 0

            if ts and ts <= self.last_ts:
                continue

            pt = bj_str_from_ts(ts) if ts else ""

            url = "#"

            intro = ""
            unscramble = item.get("newsUnscrambleModel") or {}
            if isinstance(unscramble, dict):
                intro = (unscramble.get("content") or "").strip()
            if not intro:
                ref_info = item.get("refInfo")
                if isinstance(ref_info, dict):
                    intro = (ref_info.get("brief") or ref_info.get("summary") or "").strip()

            source_name = (item.get("simWebsiteName") or "").strip()
            if source_name and source_name != "法布财经":
                title = f"[{source_name}] {title}"

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro[:150],
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        params = dict(self.source.params)
        params["pageSize"] = 50

        logger = __import__('logging').getLogger("news_monitor")
        logger.info(f"法布财经补抓模式：开始分页补抓")

        all_news = await self._paginated_fetch(
            http_client,
            self.source.url,
            params,
            page_param="pageNo",
            max_pages=50,
            items_per_page=50
        )

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"法布财经补抓完成：共获取{len(all_news)}条历史新闻")

        if all_news:
            self.last_ts = max(n.publish_ts for n in all_news if n.publish_ts > 0)

        return all_news


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

            if not re.match(r"\d{2}:\d{2}:\d{2}", time_str):
                continue

            try:
                dt = datetime.strptime(f"{today_str} {time_str}", "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=bj_tz)
                ts = int(dt.timestamp())
                pt = bj_str_from_ts(ts)
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
