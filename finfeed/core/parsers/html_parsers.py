#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML 页面类新闻源解析器"""

import re
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

import httpx
from bs4 import BeautifulSoup

from .base import BaseParser
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import (
    ts_from_bj_str, bj_str_from_ts, now_bj,
    parse_relative_time,
)
from finfeed.config.settings import get_display_name

logger = logging.getLogger("news_monitor")


class GelonghuiArticleParser(BaseParser):
    """格隆汇文章 - HTML 页面"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(response.text, "lxml")
        for article in soup.select(".article-content"):
            link_elem = article.select_one(".detail-right > a")
            if not link_elem:
                continue
            url = link_elem.get("href", "")
            if url and not url.startswith("http"):
                url = f"https://www.gelonghui.com{url}"
            title_elem = link_elem.select_one("h2")
            title = title_elem.get_text(strip=True) if title_elem else ""
            if not title:
                continue
            info_elem = article.select_one(".time > span:nth-child(1)")
            info = info_elem.get_text(strip=True) if info_elem else ""
            time_elem = article.select_one(".time > span:nth-child(3)")
            time_str = time_elem.get_text(strip=True) if time_elem else ""
            ts = parse_relative_time(time_str)
            if ts and ts <= self.last_ts:
                continue
            pt = bj_str_from_ts(ts) if ts else ""
            news_list.append(self._make_news(
                title=title[:80],
                url=url or "#",
                publish_ts=ts,
                publish_time=pt,
                intro=info[:150] if info else "",
                source_name=get_display_name(self.source.name),
            ))
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：格隆汇文章页面不支持分页，返回空"""
        return []


class FastbullParser(BaseParser):
    """法布财经 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        data = response.json()

        if data.get("code") != 0:
            return news_list

        body_raw = data.get("bodyMessage")
        if not body_raw:
            return news_list

        if isinstance(body_raw, str):
            try:
                body = json.loads(body_raw)
            except (json.JSONDecodeError, TypeError):
                return news_list
        else:
            body = body_raw

        items = body.get("pageDatas") or []
        for item in items:
            if not isinstance(item, dict):
                continue

            title = (item.get("newsTitle") or "").strip()
            if not title or len(title) < 4:
                continue

            released = item.get("releasedDate") or 0
            if isinstance(released, (int, float)):
                ts_ms = int(released)
                ts = ts_ms // 1000 if ts_ms > 1e12 else ts_ms
            else:
                ts = ts_from_bj_str(str(released)) if released else 0

            if ts and ts <= self.last_ts:
                continue

            pt = bj_str_from_ts(ts) if ts else ""

            url = "#"

            intro = ""
            unscramble = item.get("newsUnscrambleModel") or {}
            if isinstance(unscramble, dict):
                intro = (unscramble.get("content") or "").strip()
            if not intro:
                ref_info = item.get("refInfo")
                if isinstance(ref_info, dict):
                    intro = (ref_info.get("brief") or ref_info.get("summary") or "").strip()

            source_name = (item.get("simWebsiteName") or "").strip()
            if source_name and source_name != "法布财经":
                title = f"[{source_name}] {title}"

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro[:150],
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：通过分页获取历史数据"""
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        params = dict(self.source.params)
        params["pageSize"] = 50

        logger.info(f"法布财经补抓模式：开始分页补抓")

        all_news = await self._paginated_fetch(
            http_client,
            self.source.url,
            params,
            page_param="pageNo",
            max_pages=10,
            items_per_page=50
        )

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"法布财经补抓完成：共获取{len(all_news)}条历史新闻")

        return all_news


class NBDParser(BaseParser):
    """每经网 - HTML 页面"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(response.text, "lxml")
        today_str = now_bj().strftime("%Y-%m-%d")
        bj_tz = timezone(timedelta(hours=8))

        for item in soup.select("li"):
            time_elem = item.select_one(".li-title .title-p span")
            title_elem = item.select_one(".li-text h1")
            content_link = item.select_one(".li-text a.item_content")
            content_elem = item.select_one(".li-text a.item_content p")

            if not time_elem or not title_elem or not content_link:
                continue

            time_str = time_elem.get_text(strip=True)
            title = title_elem.get_text(strip=True)
            url = content_link.get("href", "#")
            content = content_elem.get_text(strip=True) if content_elem else ""

            if not title or len(title) < 4:
                continue

            try:
                if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", time_str):
                    dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    dt = dt.replace(tzinfo=bj_tz)
                    ts = int(dt.timestamp())
                    pt = bj_str_from_ts(ts)
                elif re.match(r"\d{2}:\d{2}:\d{2}", time_str):
                    dt = datetime.strptime(f"{today_str} {time_str}", "%Y-%m-%d %H:%M:%S")
                    dt = dt.replace(tzinfo=bj_tz)
                    ts = int(dt.timestamp())
                    now_ts = int(datetime.now(bj_tz).timestamp())
                    if ts > now_ts + 60:
                        dt = dt - timedelta(days=1)
                        ts = int(dt.timestamp())
                    pt = bj_str_from_ts(ts)
                else:
                    continue
            except ValueError:
                continue

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=content[:150],
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：每经网只显示当天数据，返回空"""
        return []


def _extract_time_from_parent(elem, max_levels: int = 5) -> str:
    """从元素向上查找父容器，提取时间文本"""
    container = elem
    for _ in range(max_levels):
        if container is None:
            break
        for t_elem in container.find_all(["p", "span", "div"], recursive=False):
            text = t_elem.get_text(strip=True)
            if text and len(text) < 30:
                ts = parse_relative_time(text)
                if ts > 0:
                    return text
        all_text = container.get_text(" ", strip=True)
        rel_m = re.search(r"(\d+\s*(?:分钟|小时|天)前)", all_text)
        if rel_m:
            return rel_m.group(1)
        time_m = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", all_text)
        if time_m:
            return time_m.group(1)
        date_m = re.search(r"(\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2})", all_text)
        if date_m:
            return date_m.group(1)
        container = container.parent
    return ""


class HexunParser(BaseParser):
    """和讯网 - HTML 页面（使用浏览器渲染绕过反爬虫）"""

    _RE_HEXUN_URL = re.compile(r"/(\d{4})-(\d{2})-(\d{2})/(\d+)\.html")
    _RE_CLEAN_TITLE = re.compile(r"^[•●■★◆●\s]+|[•●■★◆●\s]+$")
    _RE_OBFUSCATED = re.compile(r"<script>window\._[A-Za-z]+")

    @staticmethod
    def _is_obfuscated(html_text: str) -> bool:
        """检测页面是否被反爬混淆"""
        return bool(HexunParser._RE_OBFUSCATED.search(html_text[:500]))

    @staticmethod
    async def _fetch_with_browser(url: str, headers: dict) -> str:
        """使用浏览器渲染获取页面内容"""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=headers.get("User-Agent", ""))
                await page.goto(url, timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=15000)
                content = await page.content()
                await browser.close()
                return content
        except Exception as e:
            logger.warning(f"和讯网浏览器渲染失败: {str(e)[:80]}")
            return ""

    async def _parse_html(self, html_text: str) -> list[NewsItem]:
        """解析HTML文本提取新闻"""
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")
        bj_tz = timezone(timedelta(hours=8))

        for item in soup.find_all("a"):
            url = item.get("href", "")
            if not url:
                continue

            if url.startswith("//"):
                url = "https:" + url
            elif not url.startswith("http"):
                continue

            if "stock.hexun.com/" not in url and "news.hexun.com/" not in url:
                continue

            m = self._RE_HEXUN_URL.search(url)
            if not m:
                continue

            year, month, day, news_id = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)

            title = item.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            title = self._RE_CLEAN_TITLE.sub("", title)

            if not title or len(title) < 4:
                continue

            if "注册资本" in title or "成立" in title:
                continue

            ts = 0
            time_str = _extract_time_from_parent(item)
            if time_str:
                ts = parse_relative_time(time_str)

            if ts <= 0:
                try:
                    dt = datetime(year, month, day, 0, 0, 0, tzinfo=bj_tz)
                    ts = int(dt.timestamp())
                except ValueError:
                    continue

            pt = bj_str_from_ts(ts)

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro="",
            ))

        news_list = list({n.url: n for n in news_list}.values())
        return news_list

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        html_text = response.content.decode("gbk", errors="replace")

        if self._is_obfuscated(html_text):
            logger.info("和讯网页面被反爬混淆，尝试浏览器渲染")
            browser_html = await self._fetch_with_browser(
                self.source.url, dict(self.source.headers)
            )
            if browser_html:
                return await self._parse_html(browser_html)
            return []

        return await self._parse_html(html_text)

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：和讯网页面不支持分页，返回空"""
        return []


def _find_link_near_time(time_elem, max_levels: int = 5):
    """从时间元素向上查找包含它的链接元素"""
    container = time_elem
    for _ in range(max_levels):
        if container is None:
            break
        if container.name == "a" and container.get("href"):
            return container
        for link in container.find_all("a", href=True, recursive=False):
            return link
        container = container.parent
    return None


class IfengParser(BaseParser):
    """凤凰财经 - HTML 页面"""

    _RE_IFENG_VALID = re.compile(r"ifeng\.com/c/")

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(response.text, "lxml")

        time_elems = soup.find_all(class_=lambda x: x and "newsFeedTime" in str(x))
        seen_urls = set()

        for time_elem in time_elems:
            time_str = time_elem.get_text(strip=True)
            if not time_str:
                continue

            ts = parse_relative_time(time_str)
            if ts <= 0:
                continue

            link_elem = None
            container = time_elem
            for _ in range(5):
                if container is None:
                    break
                if container.name == "a" and container.get("href"):
                    href = container.get("href", "")
                    if self._RE_IFENG_VALID.search(href):
                        link_elem = container
                        break
                container = container.parent

            if not link_elem:
                continue

            url = link_elem.get("href", "")
            if not url:
                continue
            if url.startswith("//"):
                url = "https:" + url
            elif not url.startswith("http"):
                url = "https://finance.ifeng.com" + url
            if url in seen_urls:
                continue
            seen_urls.add(url)

            title_elem = link_elem.find(["h2", "h3", "h4", "p", "span"], class_=lambda x: x and ("title" in str(x).lower() or "name" in str(x).lower()))
            if title_elem:
                title = title_elem.get_text(strip=True)
            else:
                all_text = link_elem.get_text(" ", strip=True)
                title = re.sub(r"\d{2}-\d{2}\s+\d{2}:\d{2}.*$", "", all_text).strip()
                title = re.sub(r"\d+评$", "", title).strip()

            if not title or len(title) < 4:
                continue

            pt = bj_str_from_ts(ts)

            if ts and ts <= self.last_ts:
                continue

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro="",
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：凤凰财经页面不支持分页，返回空"""
        return []


class JiemianParser(BaseParser):
    """界面新闻 - HTML 页面"""

    _RE_JIEMIAN_URL = re.compile(r"/article/(\d+)\.html")

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(response.text, "lxml")
        today_str = now_bj().strftime("%Y-%m-%d")
        bj_tz = timezone(timedelta(hours=8))

        news_items = {}

        for t_elem in soup.find_all(["span", "div"], class_=lambda x: x and ("date" in str(x).lower() or "time" in str(x).lower())):
            time_text = t_elem.get_text(strip=True)
            if not time_text or len(time_text) > 30:
                continue

            ts = parse_relative_time(time_text)
            if ts <= 0:
                continue

            container = t_elem
            link_elem = None
            for _ in range(6):
                if container is None:
                    break
                for link in container.find_all("a", href=True):
                    href = link.get("href", "")
                    if "jiemian.com/article/" in href or (href.startswith("/article/") and href.endswith(".html")):
                        title_text = link.get_text(strip=True)
                        if title_text and len(title_text) >= 6:
                            link_elem = link
                            break
                if link_elem:
                    break
                container = container.parent

            if not link_elem:
                continue

            url = link_elem.get("href", "")
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.jiemian.com" + url

            if url not in news_items:
                title = link_elem.get_text(strip=True)
                if title and len(title) >= 4:
                    news_items[url] = (title, ts)

        for url, (title, ts) in news_items.items():
            pt = bj_str_from_ts(ts)
            if ts and ts <= self.last_ts:
                continue
            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro="",
            ))

        seen_urls = {n.url for n in news_list}
        for item in soup.find_all("a"):
            url = item.get("href", "")
            if not url:
                continue
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.jiemian.com" + url
            elif not url.startswith("http"):
                continue

            if "jiemian.com/article/" not in url:
                continue
            if url in seen_urls:
                continue

            title = item.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            ts = 0
            container = item
            for _ in range(6):
                if container is None:
                    break
                for elem in container.find_all(["span", "div", "p"], string=True):
                    text = elem.get_text(strip=True)
                    if text:
                        t_ts = parse_relative_time(text)
                        if t_ts > 0:
                            ts = t_ts
                            break
                if ts > 0:
                    break
                container = container.parent

            if ts <= 0:
                continue

            pt = bj_str_from_ts(ts)
            if ts and ts <= self.last_ts:
                continue
            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro="",
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：界面新闻页面不支持分页，返回空"""
        return []


class ThePaperParser(BaseParser):
    """澎湃新闻 - HTML 页面"""

    _RE_THEPAPER_URL = re.compile(r"/newsDetail_forward_(\d+)")

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        soup = BeautifulSoup(response.text, "lxml")
        today_str = now_bj().strftime("%Y-%m-%d")
        bj_tz = timezone(timedelta(hours=8))

        news_items = {}

        for t_elem in soup.find_all(["p", "span", "div"], class_=lambda x: x and "author_time" in str(x).lower()):
            time_text = t_elem.get_text(strip=True)
            ts = parse_relative_time(time_text)
            if ts <= 0:
                continue

            container = t_elem
            link_elem = None
            for _ in range(6):
                if container is None:
                    break
                if container.name == "a" and container.get("href"):
                    href = container.get("href", "")
                    if "newsDetail_forward_" in href:
                        link_elem = container
                        break
                for link in container.find_all("a", href=True):
                    href = link.get("href", "")
                    if "newsDetail_forward_" in href:
                        title_text = link.get_text(strip=True)
                        if title_text and len(title_text) >= 4:
                            link_elem = link
                            break
                if link_elem:
                    break
                container = container.parent

            if not link_elem:
                continue

            url = link_elem.get("href", "")
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.thepaper.cn" + url

            if url not in news_items:
                title = link_elem.get_text(strip=True)
                title = re.sub(r"^推荐", "", title).strip()
                title = re.sub(r"^\d{1,2}:\d{2}\s*", "", title).strip()
                if title and len(title) >= 4:
                    news_items[url] = (title, ts)

        for url, (title, ts) in news_items.items():
            pt = bj_str_from_ts(ts)
            if ts and ts <= self.last_ts:
                continue
            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro="",
            ))

        seen_urls = {n.url for n in news_list}
        for item in soup.find_all("a"):
            url = item.get("href", "")
            if not url:
                continue

            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = "https://www.thepaper.cn" + url
            elif not url.startswith("http"):
                continue

            if "thepaper.cn/newsDetail_forward_" not in url:
                continue
            if url in seen_urls:
                continue

            title = item.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            title = re.sub(r"^推荐", "", title).strip()
            title = re.sub(r"^\d{1,2}:\d{2}\s*", "", title).strip()
            if not title:
                continue

            ts = 0
            container = item
            for _ in range(5):
                if container is None:
                    break
                for elem in container.find_all(["p", "span", "div"]):
                    text = elem.get_text(strip=True)
                    if text:
                        t_ts = parse_relative_time(text)
                        if t_ts > 0:
                            ts = t_ts
                            break
                if ts > 0:
                    break
                container = container.parent

            if ts <= 0:
                continue

            pt = bj_str_from_ts(ts)
            if ts and ts <= self.last_ts:
                continue
            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro="",
            ))

        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：澎湃新闻页面不支持分页，返回空"""
        return []


class YicaiParser(BaseParser):
    """第一财经 - JSON API"""

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))

        try:
            data = response.json()
        except (json.JSONDecodeError, TypeError):
            return news_list

        if not isinstance(data, list):
            return news_list

        seen_urls = set()

        for item in data:
            if not isinstance(item, dict):
                continue

            title = (item.get("NewsTitle") or "").strip()
            if not title or len(title) < 4:
                continue

            url = item.get("url", "")
            if url.startswith("/"):
                url = "https://www.yicai.com" + url
            elif not url.startswith("http"):
                url = "#"

            if url in seen_urls:
                continue
            seen_urls.add(url)

            ts = 0
            create_date = item.get("CreateDate", "")
            if create_date:
                try:
                    if "T" in create_date:
                        dt = datetime.strptime(create_date, "%Y-%m-%dT%H:%M:%S")
                    else:
                        dt = datetime.strptime(create_date, "%Y-%m-%d %H:%M:%S")
                    dt = dt.replace(tzinfo=bj_tz)
                    ts = int(dt.timestamp())
                except ValueError:
                    pass

            if ts <= 0:
                datekey = item.get("datekey", "")
                hm = item.get("hm", "")
                if datekey and hm:
                    try:
                        date_str = datekey.replace(".", "-")
                        dt = datetime.strptime(f"{date_str} {hm}", "%Y-%m-%d %H:%M")
                        dt = dt.replace(tzinfo=bj_tz)
                        ts = int(dt.timestamp())
                    except ValueError:
                        pass

            if ts <= 0:
                continue

            pt = bj_str_from_ts(ts)

            if ts and ts <= self.last_ts:
                continue

            intro = ""
            content = item.get("LiveContent", "")
            if content:
                intro = re.sub(r"<[^>]+>", "", content).strip()[:150]

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
        if not self._catch_up_mode or self.last_ts <= 0:
            return []

        logger.info(f"第一财经补抓模式：开始分页补抓")

        all_news = await self._paginated_fetch(
            http_client,
            "https://www.yicai.com/api/ajax/getbrieflist",
            {"page": 1, "pagesize": 50, "id": 0},
            page_param="page",
            max_pages=10,
            items_per_page=50
        )

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"第一财经补抓完成：共获取{len(all_news)}条历史新闻")

        return all_news


class LuoBoParser(BaseParser):
    """萝卜投研 - 通过浏览器渲染捕获网络响应获取数据"""

    SOURCE_URLS = [
        "https://robo.datayes.com/",
    ]

    @staticmethod
    async def _fetch_with_browser(url: str, headers: dict) -> list:
        """使用浏览器渲染并捕获API响应数据"""
        try:
            from playwright.async_api import async_playwright

            all_data = []

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox"]
                )
                page = await browser.new_page(
                    user_agent=headers.get("User-Agent", ""),
                    viewport={"width": 1920, "height": 1080}
                )

                async def handle_response(response):
                    resp_url = response.url
                    if 'gw.datayes.com/rrp_mammon/web/feed/list' in resp_url:
                        try:
                            json_data = await response.json()
                            if json_data.get("code") == 1 and json_data.get("data"):
                                all_data.append(json_data)
                        except Exception as e:
                            logger.debug(f"萝卜投研响应解析失败: {e}")

                page.on('response', handle_response)

                await page.goto(url, timeout=60000)
                await page.wait_for_load_state("networkidle", timeout=30000)
                await page.wait_for_timeout(5000)

                await browser.close()

            return all_data
        except Exception as e:
            logger.warning(f"萝卜投研浏览器渲染失败({url}): {str(e)[:80]}")
            return []

    def _parse_feed_item(self, item: dict, bj_tz, seen_urls: set) -> Optional[NewsItem]:
        """解析feed文章数据"""
        if not isinstance(item, dict):
            return None

        feed_id = item.get("id", "")
        if not feed_id:
            return None

        title = (item.get("title", "") or "").strip()
        if not title or len(title) < 4:
            return None

        url = f"https://robo.datayes.com/v2/details/feed/{feed_id}"
        if url in seen_urls:
            return None
        seen_urls.add(url)

        ts = 0
        publish_time = item.get("publishTime", 0)
        if isinstance(publish_time, (int, float)):
            ts_ms = int(publish_time)
            ts = ts_ms // 1000 if ts_ms > 1e12 else ts_ms
        elif isinstance(publish_time, str):
            ts = ts_from_bj_str(publish_time)

        if ts <= 0:
            return None

        pt = bj_str_from_ts(ts)

        if not self._catch_up_mode and ts and ts <= self.last_ts:
            return None

        intro = ""
        content = item.get("shortDocContent", "") or item.get("description", "")
        if content:
            intro = re.sub(r"<[^>]+>", "", str(content)).strip()[:150]

        author = ""
        robo_column = item.get("roboColumn", {})
        if isinstance(robo_column, dict):
            author = robo_column.get("name", "")

        news = self._make_news(
            title=title[:80],
            url=url,
            publish_ts=ts,
            publish_time=pt,
            intro=intro,
        )
        return news

    def _parse_html_fallback(self, html_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        """从HTML页面提取新闻（备用方案）"""
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if not href:
                continue

            if href.startswith("/v2/details/feed/") or href.startswith("v2/details/feed/") or href.startswith("/v2/article/") or href.startswith("v2/article/"):
                article_id = href.replace("/v2/details/feed/", "").replace("v2/details/feed/", "").replace("/v2/article/", "").replace("v2/article/", "").strip()
                if not article_id or not article_id.isdigit():
                    continue
                url = f"https://robo.datayes.com/v2/details/feed/{article_id}"
            elif href.startswith("http") and "robo.datayes.com" in href:
                url = href
                if "/v2/details/feed/" in href:
                    article_id = href.split("/v2/details/feed/")[-1].split("/")[0]
                    url = f"https://robo.datayes.com/v2/details/feed/{article_id}"
                elif "/v2/article/" in href:
                    article_id = href.split("/v2/article/")[-1].split("/")[0]
                    url = f"https://robo.datayes.com/v2/details/feed/{article_id}"
                else:
                    continue
            else:
                continue

            if url in seen_urls:
                continue

            title = link.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            seen_urls.add(url)
            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro="",
            ))

        for h2 in soup.find_all("h2"):
            title = h2.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            link = h2.find_parent("a", href=True)
            if not link:
                continue

            href = link.get("href", "")
            if not href:
                continue

            if href.startswith("/v2/details/feed/") or href.startswith("/v2/article/"):
                article_id = href.replace("/v2/details/feed/", "").replace("/v2/article/", "").strip()
                url = f"https://robo.datayes.com/v2/details/feed/{article_id}"
            elif href.startswith("http") and "robo.datayes.com" in href:
                if "/v2/details/feed/" in href:
                    article_id = href.split("/v2/details/feed/")[-1].split("/")[0]
                    url = f"https://robo.datayes.com/v2/details/feed/{article_id}"
                elif "/v2/article/" in href:
                    article_id = href.split("/v2/article/")[-1].split("/")[0]
                    url = f"https://robo.datayes.com/v2/details/feed/{article_id}"
                else:
                    url = href
            else:
                continue

            if url in seen_urls:
                continue

            seen_urls.add(url)
            ts = int(datetime.now(bj_tz).timestamp())
            pt = bj_str_from_ts(ts)

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro="",
            ))

        return news_list

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()
        headers = dict(self.source.headers)
        logger.info(f"萝卜投研开始解析，last_ts={self.last_ts}")

        for url in self.SOURCE_URLS:
            try:
                logger.info(f"萝卜投研浏览器渲染中...")
                data_list = await self._fetch_with_browser(url, headers)
                logger.info(f"萝卜投研浏览器渲染完成，获取到 {len(data_list)} 个API响应")
                for data in data_list:
                    if not isinstance(data, dict):
                        continue
                    feed_data = data.get("data", {})
                    if not isinstance(feed_data, dict):
                        continue
                    items = feed_data.get("list", [])
                    if not isinstance(items, list):
                        continue
                    logger.info(f"萝卜投研解析到 {len(items)} 条原始数据")
                    for item in items:
                        news = self._parse_feed_item(item, bj_tz, seen_urls)
                        if news:
                            news_list.append(news)
            except Exception as e:
                logger.warning(f"萝卜投研浏览器解析失败({url}): {str(e)[:80]}")

        logger.info(f"萝卜投研浏览器解析结果: {len(news_list)} 条")

        if not news_list:
            logger.info(f"萝卜投研浏览器解析为空，尝试HTML备用方案")
            try:
                html_news = self._parse_html_fallback(response.text, bj_tz, seen_urls)
                logger.info(f"萝卜投研HTML备用方案解析到 {len(html_news)} 条")
                news_list.extend(html_news)
            except Exception as e:
                logger.warning(f"萝卜投研HTML解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"萝卜投研最终解析结果: {len(news_list)} 条")
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：获取萝卜投研数据"""
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()
        headers = dict(self.source.headers)
        logger.info(f"萝卜投研补抓模式开始，_catch_up_mode={self._catch_up_mode}, last_ts={self.last_ts}")

        for url in self.SOURCE_URLS:
            try:
                logger.info(f"萝卜投研补抓浏览器渲染中...")
                data_list = await self._fetch_with_browser(url, headers)
                logger.info(f"萝卜投研补抓浏览器渲染完成，获取到 {len(data_list)} 个API响应")
                for data in data_list:
                    if not isinstance(data, dict):
                        continue
                    feed_data = data.get("data", {})
                    if not isinstance(feed_data, dict):
                        continue
                    items = feed_data.get("list", [])
                    if not isinstance(items, list):
                        continue
                    logger.info(f"萝卜投研补抓解析到 {len(items)} 条原始数据")
                    for item in items:
                        news = self._parse_feed_item(item, bj_tz, seen_urls)
                        if news:
                            news_list.append(news)
            except Exception as e:
                logger.warning(f"萝卜投研补抓失败({url}): {str(e)[:80]}")

        logger.info(f"萝卜投研补抓最终结果: {len(news_list)} 条")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        if news_list:
            self.last_ts = max(n.publish_ts for n in news_list if n.publish_ts > 0)

        return news_list


class ZhongzhengParser(BaseParser):
    """中证快讯 - JS数据文件（按日期存储，支持7天补抓）"""

    CS_BASE_URL = "https://www.cs.com.cn"
    CS_SUB_ID = "2245"

    def _extract_cache_time(self, html_text: str) -> str:
        """从HTML页面提取缓存时间戳"""
        m = re.search(r'tmpCachedDatetime\s*=\s*["\'](\d+)["\']', html_text)
        if m:
            return m.group(1)
        return now_bj().strftime("%Y%m%d%H%M%S")

    def _parse_js_data(self, js_text: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        """解析JS数据文件中的MI4_PAGE_ARTICLE数组"""
        news_list = []
        
        m = re.search(r'var\s+MI4_PAGE_ARTICLE\s*=\s*(\[.*\])', js_text, re.DOTALL)
        if not m:
            return news_list

        try:
            items = json.loads(m.group(1))
        except (json.JSONDecodeError, TypeError):
            return news_list

        if not isinstance(items, list):
            return news_list

        for item in items:
            if not isinstance(item, dict):
                continue

            if item.get("isTop") == 1:
                continue

            title = (item.get("title") or "").strip()
            if not title or len(title) < 4:
                continue

            url = item.get("external_link") or item.get("url") or ""
            if not url:
                continue
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = self.CS_BASE_URL + url
            elif not url.startswith("http"):
                continue

            if "cs.com.cn" not in url or url in seen_urls:
                continue
            seen_urls.add(url)

            pub_date = item.get("pub_date", "")
            ts = 0
            pt = ""
            if pub_date:
                try:
                    if re.match(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", pub_date):
                        dt = datetime.strptime(pub_date, "%Y-%m-%d %H:%M")
                        dt = dt.replace(tzinfo=bj_tz)
                        ts = int(dt.timestamp())
                        pt = bj_str_from_ts(ts)
                except ValueError:
                    pass

            if ts <= 0:
                continue

            if not self._catch_up_mode and ts and ts <= self.last_ts:
                continue

            intro = (item.get("miSummary") or "").strip()

            news_list.append(self._make_news(
                title=title[:80],
                url=url,
                publish_ts=ts,
                publish_time=pt,
                intro=intro[:150] if intro else "",
                source_name=get_display_name(self.source.name),
            ))

        return news_list

    async def _fetch_date_data(self, http_client, date_str: str, cache_time: str, bj_tz, seen_urls: set) -> list[NewsItem]:
        """获取指定日期的数据文件"""
        url = f"{self.CS_BASE_URL}/js/{self.CS_SUB_ID}/mi4_sub_articles_{date_str}.js?v={cache_time}"
        try:
            response = await http_client.get(url, headers=dict(self.source.headers))
            if response.status_code == 200 and len(response.content) > 100:
                js_text = response.text
                return self._parse_js_data(js_text, bj_tz, seen_urls)
        except Exception as e:
            logger.debug(f"中证快讯获取{date_str}数据失败: {e}")
        return []

    def _get_http_client(self, response: httpx.Response) -> httpx.AsyncClient:
        """从response获取http_client，如果没有则创建新的"""
        client = getattr(response, 'client', None)
        if client is not None:
            return client
        return httpx.AsyncClient(
            follow_redirects=True,
            timeout=self.source.timeout or 10.0,
            verify=self.source.verify_ssl,
            headers=dict(self.source.headers),
        )

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            html_text = response.text
        except Exception:
            html_text = ""

        cache_time = self._extract_cache_time(html_text)

        http_client = self._get_http_client(response)
        own_client = http_client is not getattr(response, 'client', None)

        try:
            now = now_bj()
            days_to_fetch = 3 if not self._catch_up_mode else 1

            for days_back in range(0, days_to_fetch):
                date = now - timedelta(days=days_back)
                date_str = date.strftime("%Y%m%d")
                day_news = await self._fetch_date_data(http_client, date_str, cache_time, bj_tz, seen_urls)
                news_list.extend(day_news)
        finally:
            if own_client:
                await http_client.aclose()

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：获取最近7天的数据"""
        if not self._catch_up_mode:
            return []

        logger.info(f"中证快讯补抓模式：开始补抓最近7天数据")
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        cache_time = now_bj().strftime("%Y%m%d%H%M%S")
        now = now_bj()

        for days_back in range(0, 8):
            date = now - timedelta(days=days_back)
            date_str = date.strftime("%Y%m%d")
            day_news = await self._fetch_date_data(http_client, date_str, cache_time, bj_tz, seen_urls)
            news_list.extend(day_news)
            logger.debug(f"中证快讯补抓 {date_str}: 获取到{len(day_news)}条")
            await asyncio.sleep(0.3)

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"中证快讯补抓完成：共获取{len(news_list)}条新闻")

        if news_list:
            self.last_ts = max(n.publish_ts for n in news_list if n.publish_ts > 0)

        return news_list


class JiuyanParser(BaseParser):
    """韭研公社 - 通过浏览器渲染捕获网络响应获取数据"""

    SOURCE_URLS = [
        "https://www.jiuyangongshe.com/study_publish",
        "https://www.jiuyangongshe.com/study_hot",
        "https://www.jiuyangongshe.com/square_hot",
        "https://www.jiuyangongshe.com/",
    ]

    @staticmethod
    async def _fetch_with_browser(url: str, headers: dict) -> list:
        """使用浏览器渲染并捕获API响应数据"""
        try:
            from playwright.async_api import async_playwright

            all_data = []

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=headers.get("User-Agent", ""))

                async def handle_response(response):
                    resp_url = response.url
                    if 'app.jiuyangongshe.com' in resp_url and ('/timeline/news' in resp_url or '/article/announcement' in resp_url):
                        try:
                            json_data = await response.json()
                            if 'data' in json_data and isinstance(json_data['data'], list) and len(json_data['data']) > 0:
                                all_data.append(json_data)
                        except Exception as e:
                            logger.debug(f"九言公社响应解析失败: {e}")

                page.on('response', handle_response)

                await page.goto(url, timeout=45000)
                await page.wait_for_load_state("networkidle", timeout=20000)
                await page.wait_for_timeout(3000)

                await browser.close()

            return all_data
        except Exception as e:
            logger.warning(f"韭研公社浏览器渲染失败({url}): {str(e)[:80]}")
            return []

    def _parse_timeline_item(self, item: dict, bj_tz, seen_urls: set) -> Optional[NewsItem]:
        """解析时间轴文章数据"""
        if not isinstance(item, dict):
            return None

        article_id = item.get("article_id", "")
        if not article_id:
            return None

        title = (item.get("title", "") or "").strip()
        if not title or len(title) < 4:
            return None

        url = f"https://www.jiuyangongshe.com/a/{article_id}"
        if url in seen_urls:
            return None
        seen_urls.add(url)

        ts = 0
        timeline = item.get("timeline", {})
        create_time = timeline.get("create_time", "") or item.get("create_time", "")
        if create_time:
            try:
                dt = datetime.strptime(create_time, "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=bj_tz)
                ts = int(dt.timestamp())
            except ValueError:
                pass

        if ts <= 0:
            return None

        pt = bj_str_from_ts(ts)

        if not self._catch_up_mode and ts and ts <= self.last_ts:
            return None

        intro = ""
        content = item.get("content", "")
        if content:
            intro = re.sub(r"<[^>]+>", "", str(content)).strip()[:150]

        return self._make_news(
            title=title[:80],
            url=url,
            publish_ts=ts,
            publish_time=pt,
            intro=intro,
        )

    def _parse_announcement_item(self, item: dict, bj_tz, seen_urls: set) -> Optional[NewsItem]:
        """解析公告文章数据"""
        if not isinstance(item, dict):
            return None

        article_id = item.get("article_id", "")
        if not article_id:
            return None

        title = (item.get("title", "") or "").strip()
        if not title or len(title) < 4:
            return None

        url = f"https://www.jiuyangongshe.com/a/{article_id}"
        if url in seen_urls:
            return None
        seen_urls.add(url)

        ts = int(datetime.now(bj_tz).timestamp())
        pt = bj_str_from_ts(ts)

        return self._make_news(
            title=title[:80],
            url=url,
            publish_ts=ts,
            publish_time=pt,
            intro="",
        )

    async def _extract_news_from_data(self, data_list: list, bj_tz, seen_urls: set) -> list:
        """从API响应数据中提取新闻"""
        news_list = []
        for data in data_list:
            if not isinstance(data, dict) or "data" not in data:
                continue

            api_data = data["data"]

            if isinstance(api_data, list) and len(api_data) > 0:
                first_item = api_data[0]
                if isinstance(first_item, dict):
                    if "date" in first_item and "list" in first_item:
                        for date_item in api_data:
                            if isinstance(date_item, dict):
                                article_list = date_item.get("list", [])
                                for item in article_list:
                                    news = self._parse_timeline_item(item, bj_tz, seen_urls)
                                    if news:
                                        news_list.append(news)
                    elif "article_id" in first_item:
                        for item in api_data:
                            news = self._parse_announcement_item(item, bj_tz, seen_urls)
                            if news:
                                news_list.append(news)
                    else:
                        for item in api_data:
                            news = self._parse_timeline_item(item, bj_tz, seen_urls)
                            if not news:
                                news = self._parse_announcement_item(item, bj_tz, seen_urls)
                            if news:
                                news_list.append(news)

        return news_list

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()
        headers = dict(self.source.headers)

        for url in self.SOURCE_URLS:
            try:
                data_list = await self._fetch_with_browser(url, headers)
                url_news = await self._extract_news_from_data(data_list, bj_tz, seen_urls)
                news_list.extend(url_news)
            except Exception as e:
                logger.warning(f"韭研公社解析失败({url}): {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：获取韭研公社多个板块的数据"""
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()
        headers = dict(self.source.headers)

        for url in self.SOURCE_URLS:
            try:
                data_list = await self._fetch_with_browser(url, headers)
                url_news = await self._extract_news_from_data(data_list, bj_tz, seen_urls)
                news_list.extend(url_news)
            except Exception as e:
                logger.warning(f"韭研公社补抓失败({url}): {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        if news_list:
            self.last_ts = max(n.publish_ts for n in news_list if n.publish_ts > 0)

        return news_list


class CNStockParser(BaseParser):
    """上海证券报 - 浏览器渲染提取DOM数据"""

    async def _fetch_with_browser(self) -> list:
        """使用浏览器渲染并提取新闻数据"""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox"]
                )
                page = await browser.new_page(
                    user_agent=self.source.headers.get("User-Agent", ""),
                    viewport={"width": 1920, "height": 1080}
                )

                await page.goto(self.source.url, timeout=45000)
                await page.wait_for_load_state("networkidle", timeout=20000)
                await page.wait_for_timeout(3000)

                # 在浏览器中执行JS提取新闻数据
                news_data = await page.evaluate("""
                    () => {
                        const items = document.querySelectorAll('li.ant-timeline-item');
                        const result = [];
                        let currentYear = null;
                        let currentMonth = null;
                        let currentDay = null;

                        for (const item of items) {
                            // 提取日期标签（年月日）
                            const label = item.querySelector('.ant-timeline-item-label');
                            if (label && label.textContent.trim()) {
                                const datePs = label.querySelectorAll('p.font_dina');
                                if (datePs.length >= 2) {
                                    const ym = datePs[0].textContent.trim();
                                    const d = datePs[1].textContent.trim();
                                    const parts = ym.split('.');
                                    if (parts.length >= 2) {
                                        currentYear = parseInt(parts[0]);
                                        currentMonth = parseInt(parts[1]);
                                        currentDay = parseInt(d);
                                    }
                                }
                            }

                            // 提取时间 (HH:MM)
                            let timeText = '';
                            const timeEl = item.querySelector('.ant-timeline-item-content p.font_dina');
                            if (timeEl) {
                                timeText = timeEl.textContent.trim();
                            }

                            // 提取链接和标题内容
                            const linkEl = item.querySelector('a[href*="/commonDetail/"]');
                            let url = '';
                            let title = '';
                            let content = '';

                            if (linkEl) {
                                url = linkEl.href;
                                // 查找标题span（【】包裹的文本）
                                const spans = linkEl.querySelectorAll('span');
                                for (const span of spans) {
                                    const text = span.textContent.trim();
                                    if (text.startsWith('【') && text.endsWith('】')) {
                                        title = text;
                                        // 提取内容：克隆链接元素，移除标题span和详情链接后取文本
                                        const clone = linkEl.cloneNode(true);
                                        const allSpans = clone.querySelectorAll('span');
                                        for (const s of allSpans) {
                                            const st = s.textContent.trim();
                                            if (st === text || st.includes('详情')) {
                                                s.remove();
                                            }
                                        }
                                        content = clone.textContent.trim();
                                        break;
                                    }
                                }
                                if (!title) {
                                    title = linkEl.textContent.trim().substring(0, 80);
                                }
                            }

                            if (title && timeText && url) {
                                result.push({
                                    title: title,
                                    url: url,
                                    year: currentYear,
                                    month: currentMonth,
                                    day: currentDay,
                                    time: timeText,
                                    content: content
                                });
                            }
                        }
                        return result;
                    }
                """)

                await browser.close()
                return news_data
        except Exception as e:
            logger.warning(f"上海证券报浏览器渲染失败: {str(e)[:80]}")
            return []

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        bj_tz = timezone(timedelta(hours=8))
        seen_urls = set()

        try:
            items = await self._fetch_with_browser()
            logger.info(f"上海证券报浏览器提取到 {len(items)} 条新闻")

            for item in items:
                if not isinstance(item, dict):
                    continue

                title = (item.get("title") or "").strip()
                url = item.get("url", "")
                if not title or not url:
                    continue

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # 构建时间戳
                year = item.get("year")
                month = item.get("month")
                day = item.get("day")
                time_str = item.get("time", "")

                ts = 0
                pt = ""
                if year and month and day and time_str:
                    try:
                        dt_str = f"{year}-{month:02d}-{day:02d} {time_str}:00"
                        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                        dt = dt.replace(tzinfo=bj_tz)
                        ts = int(dt.timestamp())
                        pt = bj_str_from_ts(ts)
                    except (ValueError, TypeError):
                        pass

                if ts <= 0:
                    continue

                if not self._catch_up_mode and ts and ts <= self.last_ts:
                    continue

                content = (item.get("content") or "").strip()

                news_list.append(self._make_news(
                    title=title[:80],
                    url=url,
                    publish_ts=ts,
                    publish_time=pt,
                    intro=content[:150],
                ))
        except Exception as e:
            logger.warning(f"上海证券报解析失败: {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def fetch_with_catch_up(self, http_client) -> list[NewsItem]:
        """补抓模式：上海证券报页面不支持分页历史，返回空"""
        return []
