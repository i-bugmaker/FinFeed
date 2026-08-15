#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同花顺要闻 解析器"""

import re
import logging
import asyncio
import httpx
from ..base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, now_bj, parse_url_date
from finfeed.config.settings import get_display_name
from finfeed.config.sources import THSYC_CHANNELS, THSYC_BASE_URL
from ._shared import _RE_HHMM, _RE_MD_HHMM
logger = logging.getLogger("news_monitor")
class THSYCParser(BaseParser):
    """同花顺原创 - HTML 多栏目

    增强功能：
    - 从标题提取股票名称（格式："股票名：..."）
    - 增加摘要长度到300字符
    - 在intro中标注子栏目名称
    - 设置category和stocks字段
    - 正确处理yuanchuang和stock域名的URL
    """

    _RE_STOCK_NAME = re.compile(r"^([^：:]+)[：:]")
    _RE_STOCK_CODE_IN_TITLE = re.compile(r"[（(](\d{6})[）)]")

    def _extract_stock_from_title(self, title: str) -> tuple[str, list[str]]:
        """从标题提取股票名称和清理后的标题"""
        stocks = []
        clean_title = title

        code_match = self._RE_STOCK_CODE_IN_TITLE.search(title)
        name_match = self._RE_STOCK_NAME.match(title)

        if name_match:
            stock_name = name_match.group(1).strip()
            if stock_name and len(stock_name) <= 20:
                stocks.append(stock_name)
                clean_title = title

        if code_match:
            stock_code = code_match.group(1)
            if stock_code not in stocks:
                stocks.append(stock_code)

        return clean_title, stocks

    def _make_thsyc_news(self, title: str, url: str, publish_ts: int,
                          publish_time: str, intro: str, channel_name: str,
                          stocks: list[str]) -> NewsItem:
        """构造同花顺原创新闻条目，包含栏目和股票信息"""
        if not publish_time:
            publish_time = bj_str_from_ts(publish_ts) if publish_ts else now_bj().strftime("%Y-%m-%d %H:%M:%S")

        channel_prefix = f"【{channel_name}】" if channel_name else ""
        enhanced_intro = f"{channel_prefix}{intro}" if intro else channel_prefix

        return NewsItem(
            title=title[:100] if len(title) > 100 else title,
            url=url or "#",
            source=get_display_name(self.source.name),
            publish_time=publish_time,
            publish_ts=publish_ts,
            intro=enhanced_intro[:300] if len(enhanced_intro) > 300 else enhanced_intro,
            # 同花顺原创属文章类（长文/深度内容）→ 固定 article 分类。
            # 栏目名保留在 intro 的【栏目名】前缀中，不再占用 category 字段
            # （category 现为模块级分类标签：flash/article/forum）。
            category="article",
            stocks=stocks,
        )

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
                    summary = summary_elem.get_text(strip=True) if summary_elem else ""

                    url = title_elem.get("href", "")
                    if url:
                        url = url.replace("http://", "https://")
                        if not url.startswith("http"):
                            if url.startswith("/"):
                                url = f"https://yuanchuang.10jqka.com.cn{url}"
                            else:
                                url = f"{THSYC_BASE_URL}/{url}"

                    clean_title, stocks = self._extract_stock_from_title(title)

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
                    ch_news.append(self._make_thsyc_news(
                        title=clean_title,
                        url=url or "#",
                        publish_ts=ts,
                        publish_time=pt,
                        intro=summary,
                        channel_name=ch_name,
                        stocks=stocks,
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

        news_list = []
        _thsyc_channel_last_ts: dict[str, int] = getattr(self, '_channel_last_ts', {})
        catch_up_start_ts = self.get_catch_up_start_ts()

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
                    summary = summary_elem.get_text(strip=True) if summary_elem else ""

                    url = title_elem.get("href", "")
                    if url:
                        url = url.replace("http://", "https://")
                        if not url.startswith("http"):
                            if url.startswith("/"):
                                url = f"https://yuanchuang.10jqka.com.cn{url}"
                            else:
                                url = f"{THSYC_BASE_URL}/{url}"

                    clean_title, stocks = self._extract_stock_from_title(title)

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
                    ch_news.append(self._make_thsyc_news(
                        title=clean_title,
                        url=url or "#",
                        publish_ts=ts,
                        publish_time=pt,
                        intro=summary,
                        channel_name=ch_name,
                        stocks=stocks,
                    ))
                    page_has_new = True

                if not page_has_new:
                    break

                await asyncio.sleep(0.3)

            if ch_news:
                max_ts = max(n.publish_ts for n in ch_news if n.publish_ts > 0)
                if max_ts > 0:
                    _thsyc_channel_last_ts[ch_name] = max_ts
                news_list.extend(ch_news)
                logger.debug(f"同花顺原创补抓：{ch_name}，新增{len(ch_news)}条")

        self._channel_last_ts = _thsyc_channel_last_ts
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"同花顺原创补抓完成：共获取{len(news_list)}条历史新闻")

        if news_list:
            self.last_ts = max(n.publish_ts for n in news_list if n.publish_ts > 0)

        return news_list
