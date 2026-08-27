#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金十数据 解析器"""

import asyncio
import json
import logging
import re

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.http_utils import strip_html
from finfeed.utils.time_utils import bj_str_from_ts, ts_from_bj_str

from ..base import BaseParser

logger = logging.getLogger("news_monitor")
class Jin10Parser(BaseParser):
    """金十数据 - JavaScript 变量"""

    def _is_advertisement(self, item: dict) -> bool:
        remark = item.get("remark", [])
        if isinstance(remark, list):
            for r in remark:
                if isinstance(r, dict):
                    if r.get("type") == "link" and r.get("title") == "相关链接":
                        link = r.get("link", "")
                        if "/activities/" in link:
                            return True
        data_content = item.get("data", {})
        content = data_content.get("content", "") or ""
        if content.startswith("<a href="):
            return True
        source = data_content.get("source", "") or ""
        pic = data_content.get("pic", "") or ""
        channel = item.get("channel", [])
        if remark and not source and not pic and channel == [1]:
            return True
        return False

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        _RE_JIN10_VAR = re.compile(r"^var\s+newest\s*=\s*")
        _RE_JIN10_TITLE = re.compile(r"^【([^】]*)】(.*)$")
        text = _RE_JIN10_VAR.sub("", response.text).rstrip(";").strip()
        if not text:
            return news_list
        data = json.loads(text)
        for item in data:
            if str(item.get("type", "")).lower() in ("ad", "advert", "promotion"):
                continue
            if item.get("vip") or 5 in (item.get("channel") or []):
                continue
            if self._is_advertisement(item):
                continue
            data_content = item.get("data", {})
            title_raw = (data_content.get("title", "") or data_content.get("content", "")).strip()
            title_raw = strip_html(title_raw)
            m = _RE_JIN10_TITLE.match(title_raw)
            title, desc = (m.group(1).strip(), m.group(2).strip()) if m else (title_raw, "")
            if not title:
                continue
            ts = ts_from_bj_str(item.get("time", ""))
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            news_list.append(self._make_news(
                title=title[:80],
                url=f"https://flash.jin10.com/detail/{item.get('id', '')}",
                publish_ts=ts,
                publish_time=pt,
                intro=desc[:150] if desc else "",
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：金十数据API返回最新数据，通过多次请求尝试获取历史数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        all_news = []
        catch_up_start_ts = self.get_catch_up_start_ts()
        logger.info("金十数据补抓模式：开始获取历史数据")

        for attempt in range(3):
            try:
                resp = await http_client.get(
                    self.source.url,
                    headers=dict(self.source.headers)
                )

                if resp.status_code != 200:
                    break

                news_list = await self.parse(resp)
                if not news_list:
                    break

                filtered = [n for n in news_list if n.publish_ts > catch_up_start_ts]
                all_news.extend(filtered)
                logger.debug(f"金十数据补抓：第{attempt+1}次，新增{len(filtered)}条")

                if not filtered:
                    break

                await asyncio.sleep(1)

            except Exception as e:
                logger.warning(f"金十数据补抓失败：{str(e)[:80]}")
                break

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"金十数据补抓完成：共获取{len(all_news)}条历史新闻")

        if all_news:
            self.last_ts = max(n.publish_ts for n in all_news if n.publish_ts > 0)

        return all_news
