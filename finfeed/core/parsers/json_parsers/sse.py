#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上交所公告 解析器

数据源：上海证券交易所公告查询接口（query.sse.com.cn）
- 端点：http://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do
- 分页：pageHelp.pageSize / pageHelp.pageNo，pageHelp.data 为按证券分组的公告列表
- 时间：接口仅返回公告日期（SSEDATE），无时分秒，本解析器按固定规则合成时间戳
  （历史日期取当日 09:00:00，当日公告取当前时间以捕获盘中新增）
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, now_bj

from ..base import BaseParser, register_parser
from ._shared import TZ_BJ

logger = logging.getLogger("news_monitor")

SSE_API_URL = "http://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do"
SSE_REFERER = "http://www.sse.com.cn/disclosure/listedinfo/announcement/"
SSE_PAGE_SIZE = 50
SSE_PDF_PREFIX = "https://static.sse.com.cn"
SSE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)


@register_parser("sse")
class SseParser(BaseParser):
    """上交所公告 - 官方公告查询 JSON API

    支持离线补抓：通过日期范围查询和分页获取历史公告（最多 7 天）
    """

    def __init__(self, source):
        super().__init__(source)
        self._catch_up_mode = False
        self._catch_up_end_ts = 0

    def set_catch_up_mode(self, enabled: bool, end_ts: int = 0):
        """设置补抓模式"""
        self._catch_up_mode = enabled
        self._catch_up_end_ts = end_ts

    def _headers(self) -> dict:
        """构造请求头（带 Referer）"""
        return {
            "User-Agent": SSE_USER_AGENT,
            "Referer": SSE_REFERER,
            "Accept": "application/json, text/plain, */*",
        }

    @staticmethod
    def _synthesize_ts(ssedate: str) -> int:
        """将公告日期合成为时间戳：历史日期固定 09:00:00，当日取当前时间"""
        try:
            dt = datetime.strptime(str(ssedate).strip()[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return 0
        today = now_bj().date()
        if dt.date() == today:
            return int(now_bj().replace(tzinfo=TZ_BJ).timestamp())
        return int(dt.replace(hour=9, minute=0, second=0, tzinfo=TZ_BJ).timestamp())

    @staticmethod
    def _build_url(rel_url: str) -> str:
        """拼接公告附件完整 URL"""
        rel = (rel_url or "").strip()
        if not rel:
            return ""
        if rel.startswith("http"):
            return rel
        return f"{SSE_PDF_PREFIX}{rel}"

    async def _fetch_date_range(
        self, http_client, start_date: str, end_date: str, cutoff_ts: int
    ) -> list[NewsItem]:
        """按日期范围分页抓取公告，并按截止时间戳过滤"""
        all_news = []
        page_no = 1
        max_pages = 30
        while page_no <= max_pages:
            try:
                params = {
                    "jsonCallBack": "",
                    "isPagination": "true",
                    "pageHelp.pageSize": str(SSE_PAGE_SIZE),
                    "pageHelp.cacheSize": "1",
                    "pageHelp.pageNo": str(page_no),
                    "START_DATE": start_date,
                    "END_DATE": end_date,
                    "SECURITY_CODE": "",
                    "TITLE": "",
                    "BULLETIN_TYPE": "",
                    "stockType": "",
                }
                resp = await http_client.get(
                    SSE_API_URL, headers=self._headers(), params=params
                )
                if resp.status_code != 200:
                    break

                data = resp.json()
                page_help = data.get("pageHelp") or {}
                groups = page_help.get("data") or []
                page_count = int(page_help.get("pageCount") or 0)

                page_news = []
                for group in groups:
                    for item in group:
                        news_item = self._parse_item(item, cutoff_ts)
                        if news_item is not None:
                            page_news.append(news_item)

                all_news.extend(page_news)
                logger.debug(
                    f"上交所公告：{start_date}~{end_date} 第{page_no}页，新增{len(page_news)}条"
                )

                if not page_news or page_no >= page_count:
                    break

                page_no += 1
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.warning(f"上交所公告抓取失败：{str(e)[:80]}")
                break

        return all_news

    def _parse_item(self, item, cutoff_ts: int):
        """解析单条公告，不符合条件返回 None"""
        if not isinstance(item, dict):
            return None

        title = (item.get("TITLE") or "").strip()
        if not title:
            return None

        ts = self._synthesize_ts(item.get("SSEDATE"))
        if ts <= 0:
            return None
        if cutoff_ts > 0 and ts <= cutoff_ts:
            return None

        url = self._build_url(item.get("URL") or "")
        if not url:
            return None

        sec_code = item.get("SECURITY_CODE") or ""
        sec_name = item.get("SECURITY_NAME") or ""
        btype = item.get("BULLETIN_TYPE_DESC") or ""
        intro = " ".join(x for x in (sec_name, sec_code, btype) if x)

        return self._make_news(
            title=title[:80],
            url=url,
            publish_ts=ts,
            publish_time=bj_str_from_ts(ts),
            intro=intro[:150],
        )

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        """实时抓取：拉取当日全部公告（页面数据由 fetcher 请求得到，本解析器使用其共享客户端）"""
        http_client = getattr(response, "client", None)
        if http_client is None:
            logger.warning("上交所公告：响应未携带 HTTP 客户端，跳过")
            return []

        today_str = now_bj().strftime("%Y-%m-%d")
        return await self._fetch_date_range(
            http_client, today_str, today_str, self.last_ts
        )

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：按日期范围逐日查询历史公告（最多 7 天）"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        all_news = []
        current_date = now_bj().date()
        catch_up_start_ts = self.get_catch_up_start_ts()
        start_date = datetime.fromtimestamp(catch_up_start_ts, tz=TZ_BJ).date()

        logger.info(f"上交所公告补抓模式：从 {start_date} 到 {current_date}（最多7天）")

        day_delta = current_date - start_date
        for day_offset in range(day_delta.days + 1):
            query_date = start_date + timedelta(days=day_offset)
            date_str = query_date.strftime("%Y-%m-%d")
            day_news = await self._fetch_date_range(
                http_client, date_str, date_str, catch_up_start_ts
            )
            if day_news:
                all_news.extend(day_news)
                logger.debug(f"上交所公告补抓：{date_str} 新增{len(day_news)}条")
            await asyncio.sleep(0.3)

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"上交所公告补抓完成：共获取{len(all_news)}条历史公告")

        current_ts = int(time.time())
        if all_news:
            latest_ts = max(n.publish_ts for n in all_news if n.publish_ts > 0)
            self.last_ts = max(latest_ts, current_ts - 3600)
        else:
            self.last_ts = current_ts - 3600

        return all_news
