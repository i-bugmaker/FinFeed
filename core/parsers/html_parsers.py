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


class XueqiuParser(BaseParser):
    """雪球 - HTML 页面"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        _RE_DATE_PREFIX = re.compile(r"\d{4}-\d{2}-\d{2}")
        soup = BeautifulSoup(response.text, "lxml")
        articles = soup.select(".timeline__item, .status-item, [class*='timeline'] li, [class*='status'] li")
        if not articles:
            articles = soup.find_all("li")
        for article in articles:
            content_elem = article.select_one(".content, [class*='content'], p")
            time_elem = article.select_one(".time, [class*='time'], [class*='date']")
            title_elem = article.select_one(".title, [class*='title']")
            if not content_elem:
                continue
            content = content_elem.get_text(strip=True)[:80]
            if len(content) < 4:
                continue
            ts, pt = 0, ""
            if time_elem:
                time_text = time_elem.get_text(strip=True)
                if time_text and _RE_DATE_PREFIX.match(time_text):
                    try:
                        from datetime import datetime, timezone
                        dt = datetime.strptime(time_text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                        ts = int(dt.timestamp())
                        pt = bj_str_from_ts(ts)
                    except ValueError:
                        pass
            if ts and ts <= self.last_ts:
                continue
            link = "#"
            a_tag = article.find("a", href=True)
            if a_tag:
                link = a_tag["href"]
                if not link.startswith("http"):
                    link = f"https://xueqiu.com{link}"
            title = title_elem.get_text(strip=True) if title_elem else content[:60]
            news_list.append(self._make_news(
                title=title[:80],
                url=link,
                publish_ts=ts,
                publish_time=pt,
                intro=content[:150],
            ))
        return news_list


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

            news_id = item.get("newsId") or ""
            path = item.get("path") or ""
            if path and not path.startswith("http"):
                url = f"https://www.fastbull.cn{path}" if path.startswith("/") else f"https://www.fastbull.cn/{path}"
            elif news_id:
                url = f"https://www.fastbull.cn/news/{news_id}"
            else:
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
