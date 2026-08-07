#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新华财经 解析器"""

import re
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
from bs4 import BeautifulSoup
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.config.settings import get_display_name
logger = logging.getLogger("news_monitor")
class XinhuaCaijingParser(BaseParser):
    """新华财经（中国金融信息网 cnfin.com）- 多栏目聚合解析器

    抓取栏目：
    - HTML栏目（.ui-zxlist-item结构）：要闻、独家、宏观、股市、债市、汇市、货币、大宗、丝路、信用
    - API栏目（JSONP接口）：快讯

    特性：
    - 多栏目聚合抓取
    - 快讯使用JSONP API按日期获取
    - 发布时间格式 YYYY-MM-DD HH:MM:SS
    - HTML页面不支持7天离线补抓
    """

    _RE_DETAIL_URL = re.compile(r"/(?:\w+-lb|kx)/detail/\d{8}/\d+_1\.html")
    _RE_DJ_DETAIL_URL = re.compile(r"/dj-lb/\w+/detail/\d{8}/\d+_1\.html")
    _RE_JSONP = re.compile(r'jQuery\d+_\d+\((.*)\)', re.DOTALL)

    @staticmethod
    def _parse_jsonp(text: str) -> Optional[dict]:
        """解析JSONP响应"""
        m = XinhuaCaijingParser._RE_JSONP.search(text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

    def _parse_list_page(self, html_text: str, ch_name: str, ch_last_ts: int) -> list[NewsItem]:
        """解析单个HTML栏目页面（.ui-zxlist-item结构）"""
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")
        bj_tz = timezone(timedelta(hours=8))

        items = soup.select(".ui-zxlist-item")
        for item in items:
            title_elem = item.select_one("h3 a")
            if not title_elem:
                continue

            title = title_elem.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            url = title_elem.get("href", "")
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = CNFIN_BASE_URL + url
            elif not url.startswith("http"):
                continue

            if not (self._RE_DETAIL_URL.search(url) or self._RE_DJ_DETAIL_URL.search(url)):
                continue

            ts = 0
            pt = ""
            time_elem = item.select_one(".ui-publish")
            if time_elem:
                time_str = time_elem.get_text(strip=True)
                try:
                    dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    dt = dt.replace(tzinfo=bj_tz)
                    ts = int(dt.timestamp())
                    pt = time_str
                except ValueError:
                    pass

            if ts <= 0:
                info_elem = item.select_one(".zxlist-img-r-info")
                if info_elem:
                    info_text = info_elem.get_text(strip=True)
                    time_m = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", info_text)
                    if time_m:
                        try:
                            dt = datetime.strptime(time_m.group(1), "%Y-%m-%d %H:%M:%S")
                            dt = dt.replace(tzinfo=bj_tz)
                            ts = int(dt.timestamp())
                            pt = time_m.group(1)
                        except ValueError:
                            pass

            if ts <= 0:
                date_m = re.search(r"/detail/(\d{8})/", url)
                if date_m:
                    date_str = date_m.group(1)
                    try:
                        dt = datetime.strptime(date_str, "%Y%m%d")
                        dt = dt.replace(tzinfo=bj_tz)
                        ts = int(dt.timestamp())
                        pt = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        pass

            if ts <= 0:
                continue

            if not self._catch_up_mode and ts <= ch_last_ts:
                continue

            intro = ""
            p_elem = item.select_one("p")
            if p_elem:
                intro = p_elem.get_text(strip=True)

            channel_prefix = f"[{ch_name}]"
            enhanced_intro = f"{channel_prefix}{intro}" if intro else channel_prefix

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=enhanced_intro[:150],
                source_name=get_display_name(self.source.name),
            ))

        return news_list

    async def _fetch_flash_api(self, client, ch_last_ts: int) -> list[NewsItem]:
        """通过JSONP API获取快讯数据（按日期获取最近2天）"""
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        now = datetime.now(bj_tz)
        ch_name = "快讯"

        for day_offset in range(2):
            target_date = now - timedelta(days=day_offset)
            date_str = target_date.strftime("%Y-%m-%d")

            params = {
                "queryId": CNFIN_FLASH_QUERY_IDS,
                "type": "title",
                "sourceType": "0,1,2,3,4,5",
                "tableName": "a_cj_portal_news",
                "fields": "TitleCN,PublishedAt,Summary,WapUrl,SourceUrl",
                "pageNo": "0",
                "pageSize": "100",
                "date": date_str,
            }

            try:
                resp = await client.get(CNFIN_FLASH_API, params=params, headers=self.source.headers)
                if resp.status_code != 200:
                    continue

                data = self._parse_jsonp(resp.text)
                if not data or data.get('status') != 1:
                    continue

                inner = data.get('data', {})
                if isinstance(inner, str):
                    try:
                        inner = json.loads(inner)
                    except json.JSONDecodeError:
                        continue

                results = inner.get('results', []) if isinstance(inner, dict) else []
                if not results:
                    continue

                channel_prefix = f"[{ch_name}]"

                for item in results:
                    if not isinstance(item, dict):
                        continue

                    title = (item.get('TitleCN') or '').strip()
                    if not title or len(title) < 4:
                        continue

                    pub_str = (item.get('PublishedAt') or '').strip()
                    ts = 0
                    pt = ""
                    if pub_str:
                        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                            try:
                                dt = datetime.strptime(pub_str, fmt)
                                dt = dt.replace(tzinfo=bj_tz)
                                ts = int(dt.timestamp())
                                pt = pub_str
                                break
                            except ValueError:
                                continue

                    if ts <= 0:
                        continue

                    if not self._catch_up_mode and ts <= ch_last_ts:
                        continue

                    url = (item.get('SourceUrl') or item.get('WapUrl') or '').strip()
                    if url.startswith('http://'):
                        url = 'https://' + url[7:]
                    elif url.startswith('//'):
                        url = 'https:' + url
                    elif url.startswith('/'):
                        url = CNFIN_BASE_URL + url
                    elif not url:
                        # 无链接的快讯，用列表页URL代替
                        url = f"{CNFIN_BASE_URL}/flash/index.html"

                    summary = (item.get('Summary') or '').strip()
                    enhanced_intro = f"{channel_prefix}{summary}" if summary else channel_prefix

                    news_list.append(self._make_news(
                        title=title[:80],
                        url=url,
                        publish_ts=ts,
                        publish_time=pt,
                        intro=enhanced_intro[:150],
                        source_name=get_display_name(self.source.name),
                    ))

                await asyncio.sleep(0.2)

            except Exception as e:
                logger.debug(f"新华财经[快讯]API请求失败({date_str}): {str(e)[:60]}")

        return news_list

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        _cnfin_channel_last_ts: dict[str, int] = getattr(self, '_channel_last_ts', {})
        client = getattr(response, 'client', None)

        for idx, ch in enumerate(CNFIN_CHANNELS):
            ch_name = ch["name"]
            ch_last_ts = _cnfin_channel_last_ts.get(ch_name, 0)
            ch_type = ch.get("type", "html")
            ch_news = []

            if ch_type == "api":
                # API类型栏目（快讯）
                if not client:
                    continue
                ch_news = await self._fetch_flash_api(client, ch_last_ts)
            else:
                # HTML类型栏目
                page_url = f"{CNFIN_BASE_URL}/{ch['path']}"

                if idx == 0 and ch["path"] == "news/index.html":
                    html_text = response.text
                else:
                    if not client:
                        break
                    try:
                        resp = await client.get(page_url, headers=self.source.headers)
                    except Exception as e:
                        logger.debug(f"新华财经[{ch_name}]请求失败: {str(e)[:60]}")
                        continue
                    if resp.status_code != 200:
                        logger.debug(f"新华财经[{ch_name}] HTTP {resp.status_code}")
                        continue
                    html_text = resp.text
                    await asyncio.sleep(0.2)

                ch_news = self._parse_list_page(html_text, ch_name, ch_last_ts)

            if ch_news:
                max_ts = max(n.publish_ts for n in ch_news if n.publish_ts > 0)
                if max_ts > 0:
                    _cnfin_channel_last_ts[ch_name] = max_ts
                news_list.extend(ch_news)

        self._channel_last_ts = _cnfin_channel_last_ts

        seen_urls = set()
        unique_news = []
        for n in news_list:
            # 快讯无独立URL时用标题去重
            dedup_key = n.url if n.url != f"{CNFIN_BASE_URL}/flash/index.html" else f"flash::{n.title}"
            if dedup_key not in seen_urls:
                seen_urls.add(dedup_key)
                unique_news.append(n)

        unique_news.sort(key=lambda x: x.publish_ts, reverse=True)
        return unique_news

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：HTML页面不支持7天历史分页，返回空"""
        return []
