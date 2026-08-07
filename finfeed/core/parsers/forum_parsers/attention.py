#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""注意力热榜舆情解析器：百度财经热搜、知乎财经热榜

这两类源反映"散户注意力焦点"，与股吧讨论互补：
- 股吧 = 已有持仓者的观点/情绪
- 热榜 = 全市场人群的关注焦点（含未持仓者），是情绪扩散的前瞻信号
"""

import re
import logging
from typing import Optional
from urllib.parse import quote as urlquote

import httpx
from bs4 import BeautifulSoup, Tag

from .base import BaseHtmlForumParser, BaseJsonForumParser
from finfeed.utils.time_utils import now_bj, TZ_BJ
from .utils import extract_stocks_from_text
from .ugc_platforms import FINANCE_KEYWORDS

logger = logging.getLogger("news_monitor")


class BaiduFinanceHotParser(BaseHtmlForumParser):
    """百度财经热搜 - https://top.baidu.com/board?tab=finance
    解析热榜榜单，按财经关键词过滤，反映散户全网注意力焦点。
    """

    item_selectors = ["tr", "tbody tr", ".c-table tbody tr"]
    title_selectors = ["td.c-single-text-ellipsis a", "a"]
    link_selectors = ["td.c-single-text-ellipsis a", "a"]
    time_selectors = []
    intro_selectors = []

    def _is_finance_related(self, text: str) -> bool:
        for kw in FINANCE_KEYWORDS:
            if kw in text:
                return True
        return False

    async def parse(self, response: httpx.Response) -> list:
        news_list = []
        self._seen_urls.clear()
        try:
            html_text = response.text
            if not html_text or len(html_text) < 1000:
                try:
                    html_text = response.content.decode("utf-8", errors="ignore")
                except Exception:
                    pass
            news_list = self._parse_html(html_text)
        except Exception as e:
            logger.warning(f"{self.source.name}解析失败: {str(e)[:80]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _parse_html(self, html_text: str) -> list:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")
        rows = []
        for sel in self.item_selectors:
            try:
                found = soup.select(sel)
                if len(found) >= 3:
                    rows = found
                    break
            except Exception:
                continue
        if not rows:
            rows = soup.find_all("tr")
        if not rows:
            rows = soup.select("a")

        now_ts = int(now_bj().replace(tzinfo=TZ_BJ).timestamp())
        for rank, row in enumerate(rows, start=1):
            try:
                if isinstance(row, Tag):
                    title_el = row.select_one("td.c-single-text-ellipsis a") or row.select_one("a")
                else:
                    title_el = None
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title or len(title) < 2:
                    continue
                if not self._is_finance_related(title):
                    continue
                href = title_el.get("href", "")
                if href and href.startswith("//"):
                    href = "https:" + href
                elif href and href.startswith("/"):
                    href = "https://top.baidu.com" + href
                if not href or href.startswith("javascript:"):
                    href = "https://www.baidu.com/s?wd=" + urlquote(title)
                rank_el = row.select_one(".c-index") if isinstance(row, Tag) else None
                rank_num = rank
                if rank_el:
                    try:
                        rank_num = int(re.sub(r"\D", "", rank_el.get_text(strip=True)) or rank)
                    except ValueError:
                        pass
                heat_el = None
                if isinstance(row, Tag):
                    tds = row.find_all("td")
                    if len(tds) >= 1:
                        heat_el = tds[-1]
                heat = heat_el.get_text(strip=True) if heat_el else ""
                title_full = f"[百度热{rank_num}] {title}"
                news = self._build_news_item(
                    title=title_full,
                    url=href,
                    publish_ts=now_ts - rank_num * 10,
                    intro=heat,
                    extra_stocks=extract_stocks_from_text(title),
                )
                if news:
                    news_list.append(news)
            except Exception:
                continue
        return news_list

    def _parse_item(self, item: Tag, soup: BeautifulSoup) -> Optional[object]:
        return None


class ZhihuHotParser(BaseJsonForumParser):
    """知乎财经热榜 - https://www.zhihu.com/api/v4/feed/topstory/hot-lists/total
    需 ZHIHU_COOKIE 环境变量（知乎接口反爬，无 cookie 返回空）。
    按财经关键词过滤热榜条目，反映高质量讨论群体的关注焦点。
    """

    data_path = ["data"]
    title_key = "title"
    url_key = "url"
    time_key = ""
    intro_key = "detail_text"
    time_is_timestamp = False

    def _is_finance_related(self, text: str) -> bool:
        for kw in FINANCE_KEYWORDS:
            if kw in text:
                return True
        return False

    async def parse(self, response: httpx.Response) -> list:
        news_list = []
        self._seen_urls.clear()
        try:
            if response.status_code != 200:
                logger.warning(f"{self.source.name} HTTP {response.status_code}（可能缺 cookie）")
                return []
            data = response.json()
            items = data.get("data", []) if isinstance(data, dict) else []
            if not isinstance(items, list):
                items = []
            now_ts = int(now_bj().replace(tzinfo=TZ_BJ).timestamp())
            rank = 0
            for item in items:
                try:
                    if not isinstance(item, dict):
                        continue
                    target = item.get("target", {}) or {}
                    title = target.get("title", "") or ""
                    if not title:
                        continue
                    if not self._is_finance_related(title):
                        continue
                    rank += 1
                    detail = item.get("detail_text", "") or target.get("excerpt", "") or ""
                    detail = re.sub(r"<[^>]+>", "", str(detail)).strip()
                    tid = target.get("id", "") or item.get("id", "")
                    url = target.get("url", "") or f"https://www.zhihu.com/search?type=content&q={urlquote(title)}"
                    if not url.startswith("http"):
                        url = "https://www.zhihu.com" + url
                    heat = item.get("children", [])
                    heat_str = ""
                    if isinstance(heat, list) and heat:
                        try:
                            heat_str = str(heat[0].get("heat", ""))
                        except Exception:
                            heat_str = ""
                    title_full = f"[知乎热{rank}] {title}"
                    intro_parts = []
                    if detail:
                        intro_parts.append(detail[:80])
                    if heat_str:
                        intro_parts.append(f"热度:{heat_str}")
                    news = self._build_news_item(
                        title=title_full,
                        url=url,
                        publish_ts=now_ts - rank * 10,
                        intro=" ".join(intro_parts),
                        extra_stocks=extract_stocks_from_text(title),
                    )
                    if news:
                        news_list.append(news)
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"{self.source.name}解析失败（可能缺 cookie）: {str(e)[:60]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list
