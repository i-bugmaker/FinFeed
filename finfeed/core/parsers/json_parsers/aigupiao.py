#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""爱股票 解析器"""

import re
import json
import logging
import httpx
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts
logger = logging.getLogger("news_monitor")
class AiGuPiaoParser(BaseParser):
    """爱股票（aigupiao.com）- 要闻快讯 JSON API

    API端点: https://apis.aigupiao.com/Express/express_list/
    参数: source=pc, web_data=yes, number=N, before=timestamp
    响应: {"rslt":"succ","data":{"date-group":{"title":"...","data":[...]}}}

    每条新闻字段:
    - id: 唯一标识
    - content: HTML内容（含【标题】和正文，含股票超链接）
    - content_pc: PC版内容
    - rec_time: Unix时间戳（秒）
    - important: "yes"/"no"
    - view_num, comment_num, share_num
    - stock_info: JSON数组 [{"code":"...","name":"..."}]
    - image_1, image_2, image_3: 图片URL
    """

    _RE_TITLE_BRACKET = re.compile(r"【([^】]*)】")
    _RE_HTML_TAGS = re.compile(r"<[^>]+>")

    def _extract_title(self, content: str) -> str:
        """从content中提取【】内的标题"""
        m = self._RE_TITLE_BRACKET.search(content)
        if m:
            return m.group(1).strip()
        # 无【】标题，取纯文本前40字符
        plain = self._RE_HTML_TAGS.sub("", content).strip()
        return plain[:40] if plain else "无标题"

    def _get_intro(self, content: str, title: str) -> str:
        """获取正文简介：剔除标题和HTML标签后的纯文本"""
        # 移除【标题】
        text = self._RE_TITLE_BRACKET.sub("", content)
        # 移除HTML标签
        text = self._RE_HTML_TAGS.sub("", text)
        text = re.sub(r"\s+", " ", text).strip()
        # 移除过长的空白前缀
        return text[:150] if text else ""

    def _get_detail_url(self, item_id: str) -> str:
        """构造详情页URL"""
        return f"https://news.aigupiao.com/detail/{item_id}"

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        try:
            data = response.json()
        except (json.JSONDecodeError, TypeError):
            return news_list

        if data.get("rslt") != "succ":
            return news_list

        date_groups = data.get("data", {})
        if not isinstance(date_groups, dict):
            return news_list

        for group_key, group in date_groups.items():
            if not isinstance(group, dict):
                continue
            items = group.get("data", [])
            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue

                item_id = item.get("id", "")
                if not item_id:
                    continue

                # 解析时间
                rec_time = item.get("rec_time", "0")
                ts = 0
                try:
                    ts = int(rec_time)
                except (ValueError, TypeError):
                    pass

                if ts <= 0:
                    continue

                if ts <= self.last_ts:
                    continue

                # 优先用content字段，含HTML标签和【】标题
                content = (item.get("content") or item.get("content_pc") or "").strip()
                if not content or len(content) < 4:
                    continue

                # 提取标题和简介
                title = self._extract_title(content)
                intro = self._get_intro(content, title)

                # 获取相关内容
                view_num = item.get("view_num", "0")
                stock_info_raw = item.get("stock_info", "")
                stock_names = []
                if stock_info_raw:
                    try:
                        stocks = json.loads(stock_info_raw) if isinstance(stock_info_raw, str) else stock_info_raw
                        if isinstance(stocks, list):
                            stock_names = [s.get("name", "") for s in stocks if isinstance(s, dict) and s.get("name")]
                    except (json.JSONDecodeError, TypeError):
                        pass

                # 构建intro，添加上下文
                extra_parts = []
                if stock_names:
                    extra_parts.append("相关:" + ",".join(stock_names[:5]))
                if view_num and view_num != "0":
                    extra_parts.append(f"阅读:{view_num}")
                if extra_parts:
                    extra = " | ".join(extra_parts)
                    if intro:
                        intro = f"{intro[:120]} | {extra}"
                    else:
                        intro = extra

                pt = bj_str_from_ts(ts) if ts else ""
                url = self._get_detail_url(item_id)

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro=intro[:150],
                ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过before参数分页获取历史数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        logger.info(f"爱股票补抓模式：开始分页补抓")

        params = {"source": "pc", "web_data": "yes", "number": 50}
        all_news = await self._paginated_fetch(
            http_client,
            self.source.url,
            params,
            page_param="before",
            max_pages=10,
            items_per_page=50,
        )

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"爱股票补抓完成：共获取{len(all_news)}条历史新闻")

        return all_news
