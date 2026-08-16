#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""英为财情 Investing.com 中文快讯 解析器

英为财情官方声明不提供公开 API，但提供 RSS 订阅（Webmaster Tools）。
本解析器抓取 cn.investing.com 的 RSS 2.0 资讯流：
GET https://cn.investing.com/rss/news.rss
RSS pubDate 为 UTC 时间（实测与当前 UTC 时刻吻合），解析后统一归一化到北京时间。
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, ts_from_bj_str

from ..base import BaseParser

logger = logging.getLogger("news_monitor")


def _strip_ns(tag: str) -> str:
    """去除 XML 标签的命名空间前缀（无命名空间时原样返回）"""
    return tag.rsplit("}", 1)[-1]


def _ts_from_utc_str(s: str) -> int:
    """将 RSS pubDate（UTC，格式 YYYY-MM-DD HH:MM:SS）转为 Unix 秒级时间戳

    英为财情 RSS 的 pubDate 无时区后缀且为 UTC，不能直接套用北京时间的
    ts_from_bj_str；此处先按 UTC 解析，失败再退回通用解析。
    """
    if not s:
        return 0
    try:
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return ts_from_bj_str(s)


class InvestingCnParser(BaseParser):
    """英为财情中文快讯 - cn.investing.com RSS 2.0"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            logger.warning("英为财情：RSS 解析失败（非合法 XML）")
            return news_list
        for elem in root.iter():
            if _strip_ns(elem.tag) != "item":
                continue
            fields: dict[str, str] = {}
            for child in elem:
                fields[_strip_ns(child.tag)] = (child.text or "").strip()
            title = fields.get("title", "")
            if not title:
                continue
            ts = _ts_from_utc_str(fields.get("pubDate", ""))
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            url = fields.get("link") or "#"
            author = fields.get("author", "")
            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=author[:150] if author else "",
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：RSS 仅返回最新一批资讯，单次请求尽力补抓"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []
        try:
            resp = await http_client.get(
                self.source.url,
                headers=dict(self.source.headers),
            )
            if resp.status_code != 200:
                logger.warning(f"英为财情补抓请求失败：HTTP {resp.status_code}")
                return []
            news_list = await self.parse(resp)
            catch_up_start_ts = self.get_catch_up_start_ts()
            filtered = [n for n in news_list if n.publish_ts > catch_up_start_ts]
            if filtered:
                self.last_ts = max(n.publish_ts for n in filtered if n.publish_ts > 0)
            return filtered
        except Exception as e:
            logger.warning(f"英为财情补抓失败：{str(e)[:80]}")
            return []
