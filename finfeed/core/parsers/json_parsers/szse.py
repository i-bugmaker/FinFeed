#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深交所公告 解析器

数据源：深圳证券交易所公告查询接口（www.szse.cn）
- 端点：POST http://www.szse.cn/api/disc/announcement/annList
- 请求体：JSON {"channelCode":["listedNotice_disc"],"seDate":["YYYY-MM-DD","YYYY-MM-DD"],
  "pageSize":50,"pageNum":N}，需 Content-Type: application/json
- 响应：{"announceCount": 总数, "data": [扁平公告列表]}，按 publishTime 倒序
- 附件：attachPath 相对路径，拼接 http://disc.static.szse.cn 前缀得到 PDF 地址
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

import httpx

from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, now_bj, ts_from_bj_str

from ..base import BaseParser, register_parser
from ._shared import TZ_BJ

logger = logging.getLogger("news_monitor")

SZSE_API_URL = "http://www.szse.cn/api/disc/announcement/annList"
SZSE_REFERER = "http://www.szse.cn/disclosure/listed/notice/index.html"
SZSE_CHANNEL_CODE = "listedNotice_disc"
SZSE_PAGE_SIZE = 50
SZSE_PDF_PREFIX = "http://disc.static.szse.cn"
SZSE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)


@register_parser("szse")
class SzseParser(BaseParser):
    """深交所公告 - 官方公告查询 JSON API

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
        """构造请求头（带 Referer 与 JSON 内容类型）"""
        return {
            "User-Agent": SZSE_USER_AGENT,
            "Referer": SZSE_REFERER,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _build_url(attach_path: str) -> str:
        """拼接公告附件 PDF 完整 URL"""
        path = (attach_path or "").strip()
        if not path:
            return ""
        if path.startswith("http"):
            return path
        return f"{SZSE_PDF_PREFIX}{path}"

    async def _fetch_date_range(
        self, http_client, start_date: str, end_date: str, cutoff_ts: int
    ) -> list[NewsItem]:
        """按日期范围分页抓取公告，并按截止时间戳过滤"""
        all_news = []
        page_no = 1
        max_pages = 30
        while page_no <= max_pages:
            try:
                body = {
                    "channelCode": [SZSE_CHANNEL_CODE],
                    "seDate": [start_date, end_date],
                    "pageSize": SZSE_PAGE_SIZE,
                    "pageNum": page_no,
                }
                resp = await http_client.post(
                    SZSE_API_URL, headers=self._headers(), json=body
                )
                if resp.status_code != 200:
                    break

                data = resp.json()
                items = data.get("data") or []
                announce_count = int(data.get("announceCount") or 0)

                page_news = []
                for item in items:
                    news_item = self._parse_item(item, cutoff_ts)
                    if news_item is not None:
                        page_news.append(news_item)

                all_news.extend(page_news)
                logger.debug(
                    f"深交所公告：{start_date}~{end_date} 第{page_no}页，新增{len(page_news)}条"
                )

                if not items:
                    break
                total_pages = (announce_count + SZSE_PAGE_SIZE - 1) // SZSE_PAGE_SIZE
                if page_no >= total_pages:
                    break

                page_no += 1
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.warning(f"深交所公告抓取失败：{str(e)[:80]}")
                break

        return all_news

    def _parse_item(self, item, cutoff_ts: int):
        """解析单条公告，不符合条件返回 None"""
        if not isinstance(item, dict):
            return None

        title = (item.get("title") or "").strip()
        if not title:
            return None

        ts = ts_from_bj_str(item.get("publishTime") or "")
        if ts <= 0:
            return None
        if cutoff_ts > 0 and ts <= cutoff_ts:
            return None

        url = self._build_url(item.get("attachPath") or "")
        if not url:
            return None

        sec_code = item.get("secCode") or ""
        sec_name = item.get("secName") or ""
        content = item.get("content") or ""
        if isinstance(sec_code, list):
            sec_code = ",".join(str(x) for x in sec_code)
        if isinstance(sec_name, list):
            sec_name = ",".join(str(x) for x in sec_name)
        intro = " ".join(x for x in (str(sec_name), str(sec_code), str(content)) if x)

        return self._make_news(
            title=title[:80],
            url=url,
            publish_ts=ts,
            publish_time=bj_str_from_ts(ts),
            intro=intro[:150],
        )

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        """实时抓取：拉取当日全部公告（使用 fetcher 附加的共享客户端）"""
        http_client = getattr(response, "client", None)
        if http_client is None:
            logger.warning("深交所公告：响应未携带 HTTP 客户端，跳过")
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

        logger.info(f"深交所公告补抓模式：从 {start_date} 到 {current_date}（最多7天）")

        day_delta = current_date - start_date
        for day_offset in range(day_delta.days + 1):
            query_date = start_date + timedelta(days=day_offset)
            date_str = query_date.strftime("%Y-%m-%d")
            day_news = await self._fetch_date_range(
                http_client, date_str, date_str, catch_up_start_ts
            )
            if day_news:
                all_news.extend(day_news)
                logger.debug(f"深交所公告补抓：{date_str} 新增{len(day_news)}条")
            await asyncio.sleep(0.3)

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"深交所公告补抓完成：共获取{len(all_news)}条历史公告")

        current_ts = int(time.time())
        if all_news:
            latest_ts = max(n.publish_ts for n in all_news if n.publish_ts > 0)
            self.last_ts = max(latest_ts, current_ts - 3600)
        else:
            self.last_ts = current_ts - 3600

        return all_news
