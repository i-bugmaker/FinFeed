#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""火星财经（MarsBit）快讯 解析器

API端点: https://api.marsbit.co/info/lives/showlives
参数: currentPage, pageSize
响应: {"code":1,"msg":"ok","obj":{"currentPage":1,"pageSize":N,"recordCount":...,
      "inforList":[{"id":"...","content":"<p>【标题】正文</p>","createdTime":毫秒,
                    "tag":1,"status":1,"author":"MarsBit 快讯",...}]}}

每条快讯字段:
- id: 唯一标识，详情页 URL 为 https://news.marsbit.co/flash/{id}.html
- content: HTML 内容，含【标题】与正文（标题与正文同为一条快讯）
- createdTime: Unix 毫秒时间戳（13 位，需除以 1000 转秒）
- status: 1 为正常
- tag / channelId: 频道与标签分类
"""

import json
import logging
import re

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.http_utils import strip_html
from finfeed.utils.time_utils import bj_str_from_ts

from ..base import BaseParser

logger = logging.getLogger("news_monitor")


class MarsbitParser(BaseParser):
    """火星财经（MarsBit）- 7×24 快讯 JSON API"""

    _RE_TITLE_BRACKET = re.compile(r"【([^】]*)】")

    def _extract_title(self, content: str) -> str:
        """从纯文本中提取【】内的标题"""
        m = self._RE_TITLE_BRACKET.search(content)
        if m:
            title = m.group(1).strip()
            return title if title else content[:40]
        return content[:40] if content else ""

    def _get_intro(self, content: str, title: str) -> str:
        """获取正文简介：剔除标题和 HTML 标签后的纯文本"""
        text = self._RE_TITLE_BRACKET.sub("", content)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:150] if text else ""

    def _get_detail_url(self, item_id: str) -> str:
        """构造详情页 URL"""
        return f"https://news.marsbit.co/flash/{item_id}.html"

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        try:
            data = response.json()
        except (json.JSONDecodeError, TypeError):
            return news_list

        if data.get("code") != 1:
            return news_list

        obj = data.get("obj", {})
        if not isinstance(obj, dict):
            return news_list

        items = obj.get("inforList", [])
        if not isinstance(items, list):
            return news_list

        for item in items:
            if not isinstance(item, dict):
                continue

            item_id = item.get("id", "")
            if not item_id:
                continue

            # 时间：createdTime 为毫秒时间戳
            created_ms = item.get("createdTime", 0)
            try:
                ts = int(created_ms) // 1000
            except (ValueError, TypeError):
                ts = 0
            if ts <= 0:
                continue

            if ts <= self.last_ts:
                continue

            content_raw = (item.get("content") or "").strip()
            if not content_raw:
                continue

            plain = strip_html(content_raw)
            plain = re.sub(r"\s+", " ", plain).strip()
            if not plain:
                continue

            title = self._extract_title(plain)
            intro = self._get_intro(plain, title)
            if not title:
                continue

            pt = bj_str_from_ts(ts) if ts else ""
            news_list.append(self._make_news(
                title=title[:80],
                url=self._get_detail_url(item_id),
                publish_ts=ts,
                publish_time=pt,
                intro=intro[:150],
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：按 currentPage 分页获取历史数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        logger.info("火星财经补抓模式：开始分页补抓")

        params = dict(self.source.params or {})
        params.setdefault("currentPage", 1)
        params.setdefault("pageSize", 50)

        all_news = await self._paginated_fetch(
            http_client,
            self.source.url,
            params,
            page_param="currentPage",
            max_pages=20,
            items_per_page=50,
        )

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"火星财经补抓完成：共获取{len(all_news)}条历史新闻")

        return all_news
