#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSON API 类新闻源解析器"""

import re
import json
import time
from datetime import datetime, timedelta, timezone

_RE_HHMM = re.compile(r"(\d{1,2}):(\d{2})")
_RE_MD_HHMM = re.compile(r"(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})")
TZ_BJ = timezone(timedelta(hours=8))

import httpx

from .base import BaseParser
from storage.models import NewsItem
from utils.time_utils import ts_from_bj_str, bj_str_from_ts, now_bj, parse_url_date
from utils.http_utils import strip_html
from config.settings import get_display_name
from config.sources import THSYC_CHANNELS, THSYC_BASE_URL


class SinaParser(BaseParser):
    """新浪财经 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        for a in data.get("result", {}).get("data", []):
            ctime = a.get("ctime", "")
            ts = int(ctime) if ctime and str(ctime).isdigit() else 0
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            news_list.append(self._make_news(
                title=(a.get("title") or "无标题").strip(),
                url=a.get("url", "#"),
                publish_ts=ts,
                publish_time=pt,
                intro=(a.get("intro", "") or "")[:150],
            ))
        return news_list


class CLSParser(BaseParser):
    """财联社 - JSON API（需签名认证）"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        for a in data.get("data", {}).get("roll_data", []):
            ctime = a.get("ctime", "")
            ts = int(ctime) if ctime and str(ctime).isdigit() else 0
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            title = (a.get("title") or a.get("brief", "") or "无标题").strip()[:50]
            url = f"https://www.cls.cn/detail/{a.get('id', '')}" if a.get("id") else (a.get("shareurl", "#"))
            news_list.append(self._make_news(
                title=title or "无标题",
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=(a.get("brief", "") or a.get("content", "") or "")[:150],
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过last_time参数获取历史数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        import asyncio
        import hashlib
        from urllib.parse import urlencode

        all_news = []
        catch_up_start_ts = self.get_catch_up_start_ts()
        current_last_time = catch_up_start_ts
        logger = __import__('logging').getLogger("news_monitor")
        logger.info(f"财联社补抓模式：从 {bj_str_from_ts(catch_up_start_ts)} 开始")

        max_rounds = 50
        round_num = 1
        while round_num <= max_rounds:
            try:
                cls_params = {
                    "app": "CailianpressWeb",
                    "os": "web",
                    "sv": "8.4.6",
                    "rn": "20",
                    "last_time": str(int(current_last_time)),
                }
                qs = urlencode(sorted(cls_params.items()))
                cls_params["sign"] = hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()

                resp = await http_client.get(
                    self.source.url,
                    headers=dict(self.source.headers),
                    params=cls_params
                )

                if resp.status_code != 200:
                    break

                news_list = await self.parse(resp)
                if not news_list:
                    break

                all_news.extend(news_list)
                logger.debug(f"财联社补抓：第{round_num}轮，新增{len(news_list)}条")

                min_ts = min(n.publish_ts for n in news_list if n.publish_ts > 0)
                if min_ts <= catch_up_start_ts or min_ts == current_last_time:
                    break

                current_last_time = min_ts
                round_num += 1
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.warning(f"财联社补抓失败：{str(e)[:80]}")
                break

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"财联社补抓完成：共获取{len(all_news)}条历史新闻")

        if all_news:
            self.last_ts = max(n.publish_ts for n in all_news if n.publish_ts > 0)

        return all_news


class THSParser(BaseParser):
    """同花顺 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        _RE_SHARE_URL = re.compile(r"/share/(\d+)/?")
        for a in data.get("data", {}).get("list", []):
            ctime = a.get("ctime", "")
            ts = int(ctime) if ctime and str(ctime).isdigit() else 0
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            share_url = a.get("shareUrl", "")
            url = "#"
            if share_url and "/share/" in share_url:
                m = _RE_SHARE_URL.search(share_url)
                if m:
                    aid = m.group(1)
                    date_str = bj_str_from_ts(ts)[:10].replace("-", "")
                    url = f"https://news.10jqka.com.cn/{date_str}/c{aid}.shtml"
                else:
                    url = share_url
            elif share_url:
                url = share_url
            news_list.append(self._make_news(
                title=(a.get("title") or "无标题").strip(),
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=(a.get("digest", "") or a.get("short", "") or "")[:150],
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        params = dict(self.source.params)
        return await self._catch_up_paginated(
            http_client, self.source.url, params,
            page_param="page", max_pages=50, items_per_page=20
        )


class EastMoneyParser(BaseParser):
    """东方财富 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        for a in data.get("data", {}).get("fastNewsList", []):
            st = a.get("showTime", "")
            ts = ts_from_bj_str(st)
            if ts and ts <= self.last_ts:
                continue
            pt = st[:19] if st else ""
            code = a.get("code", "")
            url = f"https://finance.eastmoney.com/a/{code}.html" if code else "#"
            news_list.append(self._make_news(
                title=(a.get("title") or "无标题").strip(),
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=(a.get("summary", "") or "")[:150],
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：东方财富API不支持分页，尝试获取当前数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        try:
            resp = await http_client.get(
                self.source.url,
                headers=dict(self.source.headers),
                params=dict(self.source.params)
            )

            if resp.status_code != 200:
                return []

            news_list = await self.parse(resp)
            catch_up_start_ts = self.get_catch_up_start_ts()
            filtered = [n for n in news_list if n.publish_ts > catch_up_start_ts]

            if filtered:
                self.last_ts = max(n.publish_ts for n in filtered if n.publish_ts > 0)

            return filtered

        except Exception:
            return []


class Jingji21Parser(BaseParser):
    """21经济网 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        for item in data.get("list", []):
            title = (item.get("title") or "").strip()
            if not title:
                continue
            time_str = item.get("inputtime", "") or ""
            if time_str and len(time_str) == 16:
                time_str += ":00"
            ts = ts_from_bj_str(time_str)
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            url = item.get("url", "") or "#"
            intro = re.sub(r"\s+", " ", (item.get("content") or "").strip())[:150]
            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        params = dict(self.source.params)
        return await self._catch_up_paginated(
            http_client, self.source.url, params,
            page_param="page", max_pages=50, items_per_page=20
        )


class WallStreetCNParser(BaseParser):
    """华尔街见闻 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        for a in data.get("data", {}).get("items", []):
            if a.get("resource_type") in ("theme", "ad"):
                continue
            resource = a.get("resource", {})
            title = (resource.get("title", "") or resource.get("content_short", "")).strip()
            if not title:
                continue
            display_time = resource.get("display_time", 0)
            ts = int(display_time) if display_time else 0
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            url = resource.get("uri", "")
            if url and not url.startswith("http"):
                url = f"https://wallstreetcn.com{url}"
            news_list.append(self._make_news(
                title=title[:80],
                url=url or "#",
                publish_ts=ts,
                publish_time=pt,
                intro=(resource.get("content_short", "") or "")[:150],
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        params = {"channel": "global-channel", "accept": "article", "limit": 30}
        return await self._catch_up_paginated(
            http_client, self.source.url, params,
            page_param="page", max_pages=30, items_per_page=30
        )


class Jin10Parser(BaseParser):
    """金十数据 - JavaScript 变量"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        _RE_JIN10_VAR = re.compile(r"^var\s+newest\s*=\s*")
        _RE_JIN10_TITLE = re.compile(r"^【([^】]*)】(.*)$")
        text = _RE_JIN10_VAR.sub("", response.text).rstrip(";").strip()
        if not text:
            return news_list
        data = json.loads(text)
        for item in data:
            if str(item.get("type", "")).lower() in ("ad", "advert", "promotion"):
                continue
            if item.get("vip") or 5 in (item.get("channel") or []):
                continue
            data_content = item.get("data", {})
            title_raw = (data_content.get("title", "") or data_content.get("content", "")).strip()
            if any(kw in title_raw for kw in ("VIP会员", "立减", "开通>>", "折扣")):
                continue
            title_raw = strip_html(title_raw)
            m = _RE_JIN10_TITLE.match(title_raw)
            title, desc = (m.group(1).strip(), m.group(2).strip()) if m else (title_raw, "")
            if not title:
                continue
            ts = ts_from_bj_str(item.get("time", ""))
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            news_list.append(self._make_news(
                title=title[:80],
                url=f"https://flash.jin10.com/detail/{item.get('id', '')}",
                publish_ts=ts,
                publish_time=pt,
                intro=desc[:150] if desc else "",
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：金十数据API返回最新数据，通过多次请求尝试获取历史数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        import asyncio
        all_news = []
        catch_up_start_ts = self.get_catch_up_start_ts()
        logger = __import__('logging').getLogger("news_monitor")
        logger.info(f"金十数据补抓模式：开始获取历史数据")

        for attempt in range(3):
            try:
                resp = await http_client.get(
                    self.source.url,
                    headers=dict(self.source.headers)
                )

                if resp.status_code != 200:
                    break

                news_list = await self.parse(resp)
                if not news_list:
                    break

                filtered = [n for n in news_list if n.publish_ts > catch_up_start_ts]
                all_news.extend(filtered)
                logger.debug(f"金十数据补抓：第{attempt+1}次，新增{len(filtered)}条")

                if not filtered:
                    break

                await asyncio.sleep(1)

            except Exception as e:
                logger.warning(f"金十数据补抓失败：{str(e)[:80]}")
                break

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"金十数据补抓完成：共获取{len(all_news)}条历史新闻")

        if all_news:
            self.last_ts = max(n.publish_ts for n in all_news if n.publish_ts > 0)

        return all_news


class GelonghuiLiveParser(BaseParser):
    """格隆汇快讯 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()
        items = data.get("result") or []
        for item in items:
            ts = item.get("createTimestamp", 0)
            if not isinstance(ts, int) or ts <= 0:
                continue
            if ts <= self.last_ts:
                continue
            title = (item.get("title") or "").strip()
            content = (item.get("content") or "").strip()
            if not title and not content:
                continue
            if not title:
                title = content[:80]
            pt = bj_str_from_ts(ts)
            route = item.get("route", "")
            url = f"https://www.gelonghui.com{route}" if route and not route.startswith("http") else (route or "#")
            stocks = item.get("relatedStocks") or []
            intro = ", ".join(s.get("name", "") for s in stocks if s.get("name")) if stocks else ""
            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro[:150],
                source_name=get_display_name(self.source.name),
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        params = dict(self.source.params)
        params["limit"] = 50
        return await self._catch_up_paginated(
            http_client, self.source.url, params,
            page_param="page", max_pages=50, items_per_page=50
        )


class QCCParser(BaseParser):
    """企查查 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        _RE_QCC_ID = re.compile(r'[?&]id=([a-f0-9]+)')
        data = response.json()
        if not isinstance(data, list):
            data = []
        for item in data:
            ts_ms = item.get("publish_time", 0)
            ts = ts_ms // 1000 if ts_ms > 1e12 else (int(ts_ms) if ts_ms else 0)
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            fd = item.get("feed_data") or {}
            links = fd.get("links") or []
            title = links[0].get("title", "").strip() if links else ""
            if not title:
                title = strip_html(fd.get("content", "")).strip()[:60]
            if not title:
                continue
            news_id = item.get("news_id", "")
            if not news_id and links:
                m = _RE_QCC_ID.search(links[0].get("url", ""))
                news_id = m.group(1) if m else ""
            url = f"https://news.qcc.com/postnews/{news_id}.html?pageSource=dynamic" if news_id else (links[0].get("url", "#") if links else "#")
            intro = strip_html(fd.get("content", "")).strip()
            intro = re.sub(r"\s+", " ", intro)[:150]
            news_list.append(self._make_news(
                title=title[:80],
                url=url or "#",
                publish_ts=ts,
                publish_time=pt,
                intro=intro,
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        params = dict(self.source.params)
        params["pageSize"] = 50
        return await self._catch_up_paginated(
            http_client, self.source.url, params,
            page_param="firstRankIndex", max_pages=30, items_per_page=50
        )


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

        import asyncio
        all_news = []
        current_date = now_bj().date()
        catch_up_start_ts = self.get_catch_up_start_ts()
        start_date = datetime.fromtimestamp(catch_up_start_ts, tz=TZ_BJ).date()

        logger = __import__('logging').getLogger("news_monitor")
        logger.info(f"巨潮公告补抓模式：从 {start_date} 到 {current_date}（最多7天）")

        date_delta = current_date - start_date
        for day_offset in range(date_delta.days + 1):
            query_date = start_date + timedelta(days=day_offset)
            date_str = query_date.strftime("%Y-%m-%d")
            se_date = f"{date_str}~{date_str}"

            page_num = 1
            max_pages = 50
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


class THSYCParser(BaseParser):
    """同花顺原创 - HTML 多栏目"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        _thsyc_channel_last_ts: dict[str, int] = getattr(self, '_channel_last_ts', {})

        for ch in THSYC_CHANNELS:
            ch_name = ch["name"]
            ch_last_ts = _thsyc_channel_last_ts.get(ch_name, 0)
            max_pages = 5
            ch_news = []

            for page in range(1, max_pages + 1):
                page_url = f"{THSYC_BASE_URL}/{ch['path']}/" if page == 1 else f"{THSYC_BASE_URL}/{ch['path']}/index_{page}.shtml"
                try:
                    resp = await response.client.get(page_url, headers=self.source.headers)
                except Exception:
                    break
                if resp.status_code != 200:
                    break

                html_text = resp.content.decode("gbk", errors="replace")
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html_text, "lxml")
                items = soup.select(".list-con ul li")
                if not items:
                    break

                page_has_new = False
                for item in items:
                    title_elem = item.select_one(".arc-title a")
                    if not title_elem:
                        continue
                    title = title_elem.get_text(strip=True)
                    if not title:
                        continue

                    time_elem = item.select_one(".arc-title span")
                    summary_elem = item.select_one(".arc-cont")
                    time_str = time_elem.get_text(strip=True) if time_elem else ""
                    summary = summary_elem.get_text(strip=True)[:150] if summary_elem else ""

                    url = title_elem.get("href", "")
                    if url and not url.startswith("http"):
                        url = f"{THSYC_BASE_URL}{url}" if url.startswith("/") else url

                    ts = 0
                    url_str = str(url)
                    date_info = parse_url_date(url_str)
                    if date_info:
                        year, month, day = date_info
                        time_m = _RE_HHMM.search(time_str.strip())
                        hour = int(time_m.group(1)) if time_m else 0
                        minute = int(time_m.group(2)) if time_m else 0
                        dt = now_bj().replace(year=year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
                        ts = int(dt.replace(tzinfo=None).timestamp())
                    else:
                        m = _RE_MD_HHMM.match(time_str.strip())
                        if m:
                            now = now_bj()
                            month, day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                            dt = now.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
                            if dt > now:
                                dt = dt.replace(year=dt.year - 1)
                            ts = int(dt.replace(tzinfo=None).timestamp())

                    if ts <= ch_last_ts:
                        continue

                    pt = bj_str_from_ts(ts) if ts else ""
                    ch_news.append(self._make_news(
                        title=title[:80],
                        url=url or "#",
                        publish_ts=ts,
                        publish_time=pt,
                        intro=summary,
                    ))
                    page_has_new = True

                if not page_has_new:
                    break

            if ch_news:
                max_ts = max(n.publish_ts for n in ch_news if n.publish_ts > 0)
                if max_ts > 0:
                    _thsyc_channel_last_ts[ch_name] = max_ts
                news_list.extend(ch_news)

        self._channel_last_ts = _thsyc_channel_last_ts
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过多栏目分页获取历史数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        import asyncio
        news_list = []
        _thsyc_channel_last_ts: dict[str, int] = getattr(self, '_channel_last_ts', {})
        catch_up_start_ts = self.get_catch_up_start_ts()

        logger = __import__('logging').getLogger("news_monitor")
        logger.info(f"同花顺原创补抓模式：开始分页补抓")

        for ch in THSYC_CHANNELS:
            ch_name = ch["name"]
            ch_news = []
            max_pages = 20

            for page in range(1, max_pages + 1):
                page_url = f"{THSYC_BASE_URL}/{ch['path']}/" if page == 1 else f"{THSYC_BASE_URL}/{ch['path']}/index_{page}.shtml"
                try:
                    resp = await http_client.get(page_url, headers=self.source.headers)
                except Exception:
                    break
                if resp.status_code != 200:
                    break

                html_text = resp.content.decode("gbk", errors="replace")
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html_text, "lxml")
                items = soup.select(".list-con ul li")
                if not items:
                    break

                page_has_new = False
                for item in items:
                    title_elem = item.select_one(".arc-title a")
                    if not title_elem:
                        continue
                    title = title_elem.get_text(strip=True)
                    if not title:
                        continue

                    time_elem = item.select_one(".arc-title span")
                    summary_elem = item.select_one(".arc-cont")
                    time_str = time_elem.get_text(strip=True) if time_elem else ""
                    summary = summary_elem.get_text(strip=True)[:150] if summary_elem else ""

                    url = title_elem.get("href", "")
                    if url and not url.startswith("http"):
                        url = f"{THSYC_BASE_URL}{url}" if url.startswith("/") else url

                    ts = 0
                    url_str = str(url)
                    date_info = parse_url_date(url_str)
                    if date_info:
                        year, month, day = date_info
                        time_m = _RE_HHMM.search(time_str.strip())
                        hour = int(time_m.group(1)) if time_m else 0
                        minute = int(time_m.group(2)) if time_m else 0
                        dt = now_bj().replace(year=year, month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
                        ts = int(dt.replace(tzinfo=None).timestamp())
                    else:
                        m = _RE_MD_HHMM.match(time_str.strip())
                        if m:
                            now = now_bj()
                            month, day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                            dt = now.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
                            if dt > now:
                                dt = dt.replace(year=dt.year - 1)
                            ts = int(dt.replace(tzinfo=None).timestamp())

                    if ts <= catch_up_start_ts:
                        continue

                    pt = bj_str_from_ts(ts) if ts else ""
                    ch_news.append(self._make_news(
                        title=title[:80],
                        url=url or "#",
                        publish_ts=ts,
                        publish_time=pt,
                        intro=summary,
                    ))
                    page_has_new = True

                if not page_has_new:
                    break

                await asyncio.sleep(0.3)

            if ch_news:
                news_list.extend(ch_news)
                logger.debug(f"同花顺原创补抓：{ch_name}，新增{len(ch_news)}条")

        self._channel_last_ts = _thsyc_channel_last_ts
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"同花顺原创补抓完成：共获取{len(news_list)}条历史新闻")

        if news_list:
            self.last_ts = max(n.publish_ts for n in news_list if n.publish_ts > 0)

        return news_list
