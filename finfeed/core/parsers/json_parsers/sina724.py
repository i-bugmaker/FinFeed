#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新浪财经 7×24 直播快讯 解析器

数据源页面: https://zhibo.sina.com.cn/finance/152
后端接口(GET): https://zhibo.sina.com.cn/api/zhibo/feed
必需参数: page(从1递增向前翻页) / page_size / zhibo_id=152 / tag_id=0 / dire=f / dpc=1
响应结构: {"result":{"status":{"code":0,"msg":"OK"},"data":{"feed":{"list":[...]}}}}
快讯字段: id / rich_text / create_time / tag / is_delete / ext(JSON字符串) / docurl
rich_text 两种形态：
  - 【标题】正文...
  - 无【】前缀，整段为内容（取首句作为标题，其余作正文）
详情页 URL 规则: ext.docurl（桌面版）→ docurl（移动版）
说明: 接口支持 page 参数向前翻页，补抓采用分页模式（_catch_up_paginated）。
"""

import json
import logging
import re

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.http_utils import strip_html
from finfeed.utils.time_utils import bj_str_from_ts, ts_from_bj_str

from ..base import BaseParser

logger = logging.getLogger("news_monitor")

_RE_BRACKET_TITLE = re.compile(r"^【([^】]*)】")
_RE_SENTENCE_END = re.compile(r"[。！？]")


class Sina724Parser(BaseParser):
    """新浪财经 7×24 直播 - zhibo.sina.com.cn/api/zhibo/feed JSON 接口"""

    def _split_title_intro(self, rich_text: str) -> tuple[str, str]:
        """从直播文本拆出标题与正文

        rich_text 两种形态：
          - 【标题】正文...
          - 无【】前缀，整段为内容（取首句作标题，其余作正文）
        """
        text = strip_html(rich_text or "").replace("\r\n", "\n").strip()
        if not text:
            return "", ""
        m = _RE_BRACKET_TITLE.match(text)
        if m:
            title = m.group(1).strip()
            return title, text[m.end():].strip()
        # 无【】前缀：取首个句子作为标题（最长 60 字），其余作正文
        m_end = _RE_SENTENCE_END.search(text)
        if m_end and m_end.start() < 60:
            title = text[: m_end.end()].strip()
            return title, text[m_end.end():].strip()
        return text[:60].strip(), text[60:].strip()

    @staticmethod
    def _get_detail_url(item: dict) -> str:
        """取详情页 URL：优先桌面版 ext.docurl，其次移动版 docurl"""
        ext_raw = item.get("ext") or ""
        try:
            ext = json.loads(ext_raw) if isinstance(ext_raw, str) else (ext_raw or {})
        except (ValueError, TypeError):
            ext = {}
        if isinstance(ext, dict):
            ext_url = ext.get("docurl")
            if ext_url:
                return ext_url
        return item.get("docurl") or "#"

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list: list[NewsItem] = []
        try:
            data = response.json()
        except ValueError as e:
            logger.warning(f"{self.source.name} 响应非 JSON：{str(e)[:80]}")
            return news_list
        feed = data.get("result", {}).get("data", {}).get("feed", {})
        items = feed.get("list") or []
        if not isinstance(items, list):
            return news_list
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("is_delete"):
                continue
            title, intro = self._split_title_intro(item.get("rich_text") or "")
            if not title:
                continue
            ts = ts_from_bj_str(item.get("create_time") or "")
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            news_list.append(self._make_news(
                title=title,
                url=self._get_detail_url(item),
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：page 参数向前翻页获取历史数据"""
        params = {
            "page_size": 100,
            "zhibo_id": 152,
            "tag_id": 0,
            "dire": "f",
            "dpc": 1,
        }
        return await self._catch_up_paginated(
            http_client, self.source.url, params,
            page_param="page", max_pages=15, items_per_page=100,
        )
