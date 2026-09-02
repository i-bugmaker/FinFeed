#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法布财经 解析器"""

import json
import logging

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, ts_from_bj_str

from ..base import BaseParser

logger = logging.getLogger("news_monitor")
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
                # 法布快讯为电报式条目（hasOfficialDetail=0，无详情页），
                # 标题即全文；url="#" 也无法走详情页补抓，正文在此一并落库
                content=title,
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        params = dict(self.source.params)
        params["pageSize"] = 50

        logger.info("法布财经补抓模式：开始分页补抓")

        all_news = await self._paginated_fetch(
            http_client,
            self.source.url,
            params,
            page_param="pageNo",
            max_pages=10,
            items_per_page=50
        )

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"法布财经补抓完成：共获取{len(all_news)}条历史新闻")

        return all_news
