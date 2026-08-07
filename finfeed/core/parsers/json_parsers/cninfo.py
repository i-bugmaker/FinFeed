#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""巨潮资讯 解析器"""

import re
import time
import logging
import asyncio
from datetime import datetime, timedelta
import httpx
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, now_bj
from finfeed.utils.http_utils import strip_html
from ._shared import TZ_BJ
logger = logging.getLogger("news_monitor")
class CninfoParser(BaseParser):
    """巨潮公告 - JSON API

    支持离线补抓：通过日期范围查询和分页来获取历史公告
    """

    def __init__(self, source):
        super().__init__(source)
        self._catch_up_mode = False
        self._catch_up_end_ts = 0

    def set_catch_up_mode(self, enabled: bool, end_ts: int = 0):
        """设置补抓模式"""
        self._catch_up_mode = enabled
        self._catch_up_end_ts = end_ts

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        return await self._parse_page(response)

    async def _parse_page(self, response: httpx.Response) -> list[NewsItem]:
        """解析单页数据"""
        news_list = []
        data = response.json()
        announcements = data.get("announcements") or []
        for item in announcements:
            title_raw = (item.get("announcementTitle") or "").strip()
            if not title_raw:
                continue
            title = strip_html(title_raw).strip()
            if not title:
                continue
            sec_code = item.get("secCode", "") or ""
            sec_name = item.get("secName", "") or ""
            if sec_name:
                title = re.sub(r"^" + re.escape(sec_name) + r"[：:]\s*", "", title)
                if title.startswith(sec_name):
                    title = title[len(sec_name):].lstrip()
            if sec_name:
                title = f"{sec_name}：{title}"
            current_ts = int(time.time())
            if current_ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(current_ts)
            adjunct_url = item.get("adjunctUrl", "") or ""
            if adjunct_url:
                url = f"http://static.cninfo.com.cn/{adjunct_url}"
            else:
                ann_id = item.get("announcementId", "")
                url = f"http://www.cninfo.com.cn/new/disclosure/detail?annoId={ann_id}" if ann_id else "#"
            intro = sec_code or ""
            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=current_ts,
                publish_time=pt,
                intro=intro[:150],
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：按日期范围和分页获取历史公告"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        all_news = []
        current_date = now_bj().date()
        catch_up_start_ts = self.get_catch_up_start_ts()
        start_date = datetime.fromtimestamp(catch_up_start_ts, tz=TZ_BJ).date()

        logger.info(f"巨潮公告补抓模式：从 {start_date} 到 {current_date}（最多7天）")

        date_delta = current_date - start_date
        for day_offset in range(date_delta.days + 1):
            query_date = start_date + timedelta(days=day_offset)
            date_str = query_date.strftime("%Y-%m-%d")
            se_date = f"{date_str}~{date_str}"

            page_num = 1
            max_pages = 10
            while page_num <= max_pages:
                try:
                    params = dict(self.source.params)
                    params["seDate"] = se_date
                    params["pageNum"] = str(page_num)
                    params["pageSize"] = "50"

                    resp = await http_client.post(
                        self.source.url,
                        headers=dict(self.source.headers),
                        data=params
                    )

                    if resp.status_code != 200:
                        break

                    data = resp.json()
                    announcements = data.get("announcements") or []
                    if not announcements:
                        break

                    page_news = []
                    for item in announcements:
                        title_raw = (item.get("announcementTitle") or "").strip()
                        if not title_raw:
                            continue
                        title = strip_html(title_raw).strip()
                        if not title:
                            continue
                        sec_code = item.get("secCode", "") or ""
                        sec_name = item.get("secName", "") or ""
                        if sec_name:
                            title = re.sub(r"^" + re.escape(sec_name) + r"[：:]\s*", "", title)
                            if title.startswith(sec_name):
                                title = title[len(sec_name):].lstrip()
                        if sec_name:
                            title = f"{sec_name}：{title}"
                        current_ts = int(time.time())
                        if current_ts <= catch_up_start_ts:
                            continue
                        pt = bj_str_from_ts(current_ts)
                        adjunct_url = item.get("adjunctUrl", "") or ""
                        if adjunct_url:
                            url = f"http://static.cninfo.com.cn/{adjunct_url}"
                        else:
                            ann_id = item.get("announcementId", "")
                            url = f"http://www.cninfo.com.cn/new/disclosure/detail?annoId={ann_id}" if ann_id else "#"
                        intro = sec_code or ""
                        page_news.append(self._make_news(
                            title=title[:80],
                            url=url,
                            publish_ts=current_ts,
                            publish_time=pt,
                            intro=intro[:150],
                        ))

                    if not page_news:
                        break

                    all_news.extend(page_news)
                    logger.debug(f"巨潮公告补抓：{date_str} 第{page_num}页，新增{len(page_news)}条")

                    if len(announcements) < 50:
                        break

                    page_num += 1
                    await asyncio.sleep(0.3)

                except Exception as e:
                    logger.warning(f"巨潮公告补抓失败：{str(e)[:80]}")
                    break

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"巨潮公告补抓完成：共获取{len(all_news)}条历史公告")

        current_ts = int(time.time())
        if all_news:
            latest_ts = max(n.publish_ts for n in all_news if n.publish_ts > 0)
            self.last_ts = max(latest_ts, current_ts - 3600)
        else:
            self.last_ts = current_ts - 3600

        return all_news
