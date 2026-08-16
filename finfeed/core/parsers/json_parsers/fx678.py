#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇通网 7×24 快讯 解析器

数据源页面: https://www.fx678.com/kx/
后端接口(POST): https://www.fx678.com/kx/ajax/zykx
响应结构: {"code":10,"msg":"...","data":"<JSON 字符串，快讯数组>"}，
         单次返回近 ~35 小时约 200 条快讯，不分页。
快讯字段: NEWSID / NEWS_TITLE / PUBLISHTIME / ...
NEWS_TITLE 两种形态：
  - 【标题】正文...（正文为 \r\n 分隔的多行编号列表）
  - 整行为标题（无正文）
详情页 URL 规则: https://www.fx678.com/C/{YYYYMMDD}/{NEWSID}.html
说明: 接口不支持分页参数，补抓采用单请求模式（_catch_up_single_request），
      重复请求由 parse 的增量过滤（last_ts）去重。
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


class Fx678Parser(BaseParser):
    """汇通网 7×24 快讯 - www.fx678.com/kx/ajax/zykx JSON 接口"""

    def _split_title_intro(self, raw: str) -> tuple[str, str]:
        """从快讯原始文本拆出标题与正文

        NEWS_TITLE 有两种形态：
          - 【标题】正文...（多行，正文为编号列表）
          - 整行为标题（无正文）
        """
        text = strip_html(raw or "").replace("\r\n", "\n").strip()
        if not text:
            return "", ""
        m = _RE_BRACKET_TITLE.match(text)
        if m:
            title = m.group(1).strip()
            intro = text[m.end():].strip()
            return title, intro
        lines = [ln.strip() for ln in re.split(r"\n", text) if ln.strip()]
        if len(lines) > 1:
            return lines[0], "\n".join(lines[1:])
        return lines[0] if lines else "", ""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list: list[NewsItem] = []
        try:
            data = response.json()
        except ValueError as e:
            logger.warning(f"{self.source.name} 响应非 JSON：{str(e)[:80]}")
            return news_list
        if not isinstance(data, dict) or data.get("code") != 10:
            logger.warning(f"{self.source.name} 接口返回异常：code={data.get('code') if isinstance(data, dict) else type(data).__name__} msg={data.get('msg', '') if isinstance(data, dict) else ''}")
            return news_list
        raw = data.get("data") or ""
        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (ValueError, TypeError) as e:
            logger.warning(f"{self.source.name} data 字段解析失败：{str(e)[:80]}")
            return news_list
        if not isinstance(items, list):
            return news_list
        for item in items:
            if not isinstance(item, dict):
                continue
            newsid = str(item.get("NEWSID") or "").strip()
            title_raw = item.get("NEWS_TITLE") or ""
            if not newsid or not title_raw:
                continue
            title, intro = self._split_title_intro(title_raw)
            if not title:
                continue
            ts = ts_from_bj_str(item.get("PUBLISHTIME") or "")
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            url = f"https://www.fx678.com/C/{newsid[:8]}/{newsid}.html"
            news_list.append(self._make_news(
                title=title,
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：zykx 接口不支持分页参数，采用单请求补抓

        单次请求即返回最近约 35 小时（约 200 条）完整快讯窗口，
        因此与金十/财联社一致，使用 _catch_up_single_request 而非分页补抓。
        仅在 _catch_up_mode 且已有 last_ts 时生效，重复请求由 parse 增量过滤。
        """
        return await self._catch_up_single_request(http_client, self.source.url)
