#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""港交所披露易（HKEXnews）公告解析器

数据源：https://www1.hkexnews.hk/search/titleSearchServlet.do
港交所官方公告披露源，覆盖全部在港上市公司的公告、通函、年报等申报文件。

- 端点返回 JSON：result 字段为 JSON 字符串（需二次解析），元素含
  TITLE / DATE_TIME（DD/MM/YYYY HH:MM，香港时间=UTC+8）/ STOCK_NAME /
  STOCK_CODE / FILE_LINK（相对路径，需拼接 https://www1.hkexnews.hk 前缀）。
- 分页：rowRange 控制单页条数（正常模式默认 50 条/天，保守；补抓用 1000 拉全一天）；
  历史补抓按日切片（fromDate=toDate=YYYYMMDD），每日一条请求。
- 保守策略：正常模式单次请求取当天最近 50 条，补抓模式按日回溯最多 7 天。
"""

import asyncio
import html
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import TZ_BJ, bj_str_from_ts

from ..base import BaseParser

logger = logging.getLogger("news_monitor")

HKEX_SEARCH_URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
HKEX_BASE_URL = "https://www1.hkexnews.hk"
HKEX_DEFAULT_ROW_RANGE = "50"
HKEX_CATCH_UP_ROW_RANGE = "1000"


class HkexNewsParser(BaseParser):
    """港交所披露易公告解析器（JSON API）"""

    def __init__(self, source):
        super().__init__(source)
        self._catch_up_mode = False
        self._catch_up_end_ts = 0

    def set_catch_up_mode(self, enabled: bool, end_ts: int = 0) -> None:
        """设置补抓模式"""
        self._catch_up_mode = enabled
        self._catch_up_end_ts = end_ts

    # ------------------------------------------------------------
    # 参数与解析辅助
    # ------------------------------------------------------------
    def _build_params(self, from_date: str, to_date: str, row_range: str = HKEX_DEFAULT_ROW_RANGE) -> Dict[str, str]:
        """构造标题搜索请求参数（from/to 日期格式 YYYYMMDD）"""
        return {
            "sortDir": "0",
            "sortByOptions": "DateTime",
            "category": "0",
            "market": "SEHK",
            "stockId": "-1",
            "documentType": "-1",
            "fromDate": from_date,
            "toDate": to_date,
            "title": "",
            "searchType": "1",
            "t1code": "-2",
            "t2Gcode": "-2",
            "t2code": "-2",
            "rowRange": row_range,
            "lang": "EN",
        }

    def _clean_title(self, raw: str) -> str:
        """清理标题：HTML 实体解码、去 <br/> 标签、规整空白"""
        if not raw:
            return ""
        text = html.unescape(raw)
        text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _parse_date_time(self, raw: str) -> Tuple[int, str]:
        """解析 DATE_TIME（DD/MM/YYYY HH:MM，香港时间=UTC+8=北京时间）"""
        try:
            dt = datetime.strptime(raw.strip(), "%d/%m/%Y %H:%M")
            dt = dt.replace(tzinfo=TZ_BJ)
            ts = int(dt.timestamp())
            return ts, bj_str_from_ts(ts)
        except (ValueError, TypeError):
            return 0, ""

    def _item_to_news(self, item: Dict[str, Any]) -> Optional[NewsItem]:
        """将单条公告记录转换为 NewsItem"""
        title_raw = (item.get("TITLE") or "").strip()
        if not title_raw:
            return None
        title = self._clean_title(title_raw)
        if not title:
            return None

        ts, pt = self._parse_date_time(item.get("DATE_TIME") or "")
        if ts <= 0:
            return None
        # 增量过滤：时间戳早于或等于上次更新时间则跳过
        if not self._catch_up_mode and ts and ts <= self.last_ts:
            return None

        file_link = (item.get("FILE_LINK") or "").strip()
        if file_link:
            url = file_link if file_link.startswith("http") else HKEX_BASE_URL + file_link
        else:
            url = "#"

        stock_name = (item.get("STOCK_NAME") or "").strip()
        stock_code = (item.get("STOCK_CODE") or "").strip()
        long_text = (item.get("LONG_TEXT") or "").strip()
        intro_parts = []
        if stock_code:
            intro_parts.append(stock_code)
        if stock_name:
            intro_parts.append(stock_name)
        if long_text:
            intro_parts.append(long_text)
        intro = " | ".join(p for p in intro_parts if p)

        return self._make_news(
            title=title[:80],
            url=url,
            publish_ts=ts,
            publish_time=pt,
            intro=intro[:150],
        )

    # ------------------------------------------------------------
    # 主解析入口
    # ------------------------------------------------------------
    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        """解析披露易标题搜索接口的 JSON 响应"""
        news_list: list[NewsItem] = []
        try:
            data = response.json()
        except (ValueError, TypeError) as e:
            logger.warning(f"港交所披露易响应 JSON 解析失败: {str(e)[:80]}")
            return []

        result = data.get("result")
        if isinstance(result, str):
            try:
                items = json.loads(result)
            except (ValueError, TypeError) as e:
                logger.warning(f"港交所披露易 result 字段二次解析失败: {str(e)[:80]}")
                return []
        else:
            items = result or []

        if not isinstance(items, list):
            return []

        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                news = self._item_to_news(item)
            except Exception as e:
                logger.debug(f"港交所披露易单条解析失败: {str(e)[:80]}")
                continue
            if news is not None:
                news_list.append(news)
        return news_list

    # ------------------------------------------------------------
    # 补抓支持
    # ------------------------------------------------------------
    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：按日切片回溯（最多 7 天，由 catch_up_start_ts 决定）"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        catch_up_start_ts = self.get_catch_up_start_ts()
        start_date = datetime.fromtimestamp(catch_up_start_ts, tz=TZ_BJ).date()
        today = datetime.now(TZ_BJ).date()

        logger.info(f"港交所披露易补抓模式：从 {start_date} 到 {today}")

        all_news: list[NewsItem] = []
        day_count = (today - start_date).days + 1
        for day_offset in range(day_count):
            query_date = start_date + timedelta(days=day_offset)
            date_str = query_date.strftime("%Y%m%d")
            try:
                resp = await http_client.get(
                    HKEX_SEARCH_URL,
                    headers=dict(self.source.headers),
                    params=self._build_params(date_str, date_str, HKEX_CATCH_UP_ROW_RANGE),
                )
                if resp.status_code != 200:
                    logger.warning(f"港交所披露易补抓请求失败：HTTP {resp.status_code}")
                    continue
                day_news = await self.parse(resp)
                if day_news:
                    all_news.extend(day_news)
                    logger.debug(f"港交所披露易补抓 {date_str}: {len(day_news)} 条")
            except Exception as e:
                logger.warning(f"港交所披露易补抓失败：{str(e)[:80]}")
            await asyncio.sleep(0.3)

        all_news = [n for n in all_news if n.publish_ts > catch_up_start_ts]
        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        if all_news:
            self.last_ts = max(n.publish_ts for n in all_news if n.publish_ts > 0)
        logger.info(f"港交所披露易补抓完成：共获取 {len(all_news)} 条公告")
        return all_news
