#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同花顺财经 解析器"""

import asyncio
import logging
import re

import httpx

from finfeed.config.settings import get_display_name
from finfeed.config.sources import THSFINANCE_BASE_URL, THSFINANCE_CHANNELS
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import bj_str_from_ts, now_bj, parse_url_date

from ..base import BaseParser
from ._shared import _RE_HHMM, _RE_MD_HHMM

logger = logging.getLogger("news_monitor")
class THSFinanceParser(BaseParser):
    """同花顺财经 - HTML 多栏目（news.10jqka.com.cn）

    抓取栏目：
    - 财经要闻、宏观经济、产经新闻、国际财经、金融市场
    - 公司新闻、区域经济、财经评论、财经人物

    特性：
    - 支持GBK编码
    - 支持多栏目分页抓取
    - 支持7天离线补抓
    - 从标题提取股票关联信息
    - URL统一为HTTPS
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

    def _make_thsfinance_news(self, title: str, url: str, publish_ts: int,
                               publish_time: str, intro: str, channel_name: str,
                               stocks: list[str]) -> NewsItem:
        """构造同花顺财经新闻条目，包含栏目和股票信息"""
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
            # 同花顺财经属文章类（栏目图文/深度内容）→ 固定 article 分类。
            # 栏目名保留在 intro 的【栏目名】前缀中，不再占用 category 字段
            # （category 现为模块级分类标签：flash/article/forum）。
            category="article",
            stocks=stocks,
        )

    async def _parse_channel_page(self, html_text: str, ch_name: str, ch_last_ts: int) -> list[NewsItem]:
        """解析单个栏目页面"""
        from bs4 import BeautifulSoup
        news_list = []

        soup = BeautifulSoup(html_text, "lxml")
        items = soup.select(".list-con ul li")
        if not items:
            return news_list

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
                        url = f"https://news.10jqka.com.cn{url}"
                    else:
                        url = f"{THSFINANCE_BASE_URL}/{url}"

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
            news_list.append(self._make_thsfinance_news(
                title=clean_title,
                url=url or "#",
                publish_ts=ts,
                publish_time=pt,
                intro=summary,
                channel_name=ch_name,
                stocks=stocks,
            ))

        return news_list

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        _thsf_channel_last_ts: dict[str, int] = getattr(self, '_channel_last_ts', {})
        client = getattr(response, 'client', None)

        for idx, ch in enumerate(THSFINANCE_CHANNELS):
            ch_name = ch["name"]
            ch_last_ts = _thsf_channel_last_ts.get(ch_name, 0)
            max_pages = 3
            ch_news = []

            for page in range(1, max_pages + 1):
                page_url = f"{THSFINANCE_BASE_URL}/{ch['path']}/" if page == 1 else f"{THSFINANCE_BASE_URL}/{ch['path']}/index_{page}.shtml"

                # 第一个栏目第一页使用已获取的response，避免重复请求
                if idx == 0 and page == 1:
                    html_text = response.content.decode("gbk", errors="replace")
                else:
                    if not client:
                        break
                    try:
                        resp = await client.get(page_url, headers=self.source.headers)
                    except Exception:
                        break
                    if resp.status_code != 200:
                        break
                    html_text = resp.content.decode("gbk", errors="replace")

                page_news = await self._parse_channel_page(html_text, ch_name, ch_last_ts)
                if not page_news:
                    break

                ch_news.extend(page_news)

                if len(page_news) < 20:
                    break

            if ch_news:
                max_ts = max(n.publish_ts for n in ch_news if n.publish_ts > 0)
                if max_ts > 0:
                    _thsf_channel_last_ts[ch_name] = max_ts
                news_list.extend(ch_news)

        self._channel_last_ts = _thsf_channel_last_ts
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过多栏目分页获取历史数据（支持7天）"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        news_list = []
        _thsf_channel_last_ts: dict[str, int] = getattr(self, '_channel_last_ts', {})
        catch_up_start_ts = self.get_catch_up_start_ts()

        logger.info("同花顺财经补抓模式：开始分页补抓")

        processed_channels = 0
        for ch in THSFINANCE_CHANNELS:
            ch_name = ch["name"]
            ch_news = []
            max_pages = 15

            for page in range(1, max_pages + 1):
                page_url = f"{THSFINANCE_BASE_URL}/{ch['path']}/" if page == 1 else f"{THSFINANCE_BASE_URL}/{ch['path']}/index_{page}.shtml"
                try:
                    resp = await http_client.get(page_url, headers=self.source.headers)
                except Exception:
                    break
                if resp.status_code != 200:
                    break

                html_text = resp.content.decode("gbk", errors="replace")
                page_news = await self._parse_channel_page(html_text, ch_name, catch_up_start_ts)
                if not page_news:
                    break

                ch_news.extend(page_news)

                if len(page_news) < 20:
                    break

                await asyncio.sleep(0.5)

            if ch_news:
                max_ts = max(n.publish_ts for n in ch_news if n.publish_ts > 0)
                if max_ts > 0:
                    _thsf_channel_last_ts[ch_name] = max_ts
                news_list.extend(ch_news)
                logger.debug(f"同花顺财经补抓：{ch_name}，新增{len(ch_news)}条")

            processed_channels += 1
            if processed_channels % 3 == 0:
                await asyncio.sleep(3)

        self._channel_last_ts = _thsf_channel_last_ts
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"同花顺财经补抓完成：共获取{len(news_list)}条历史新闻")

        if news_list:
            self.last_ts = max(n.publish_ts for n in news_list if n.publish_ts > 0)

        return news_list
