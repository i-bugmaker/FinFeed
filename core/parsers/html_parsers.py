#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML 页面类新闻源解析器"""

import re
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from .base import BaseParser
from storage.models import NewsItem
from utils.time_utils import (
    ts_from_bj_str, bj_str_from_ts, now_bj,
    parse_relative_time,
)
from config.settings import get_display_name


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

        logger = __import__('logging').getLogger("news_monitor")
        logger.info(f"法布财经补抓模式：开始分页补抓")

        all_news = await self._paginated_fetch(
            http_client,
            self.source.url,
            params,
            page_param="pageNo",
            max_pages=50,
            items_per_page=50
        )

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"法布财经补抓完成：共获取{len(all_news)}条历史新闻")

        if all_news:
            self.last_ts = max(n.publish_ts for n in all_news if n.publish_ts > 0)

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

            if not re.match(r"\d{2}:\d{2}:\d{2}", time_str):
                continue

            try:
                dt = datetime.strptime(f"{today_str} {time_str}", "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=bj_tz)
                ts = int(dt.timestamp())
                pt = bj_str_from_ts(ts)
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
            logger = __import__('logging').getLogger("news_monitor")
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
            logger = __import__('logging').getLogger("news_monitor")
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

        logger = __import__('logging').getLogger("news_monitor")
        logger.info(f"第一财经补抓模式：开始分页补抓")

        all_news = await self._paginated_fetch(
            http_client,
            "https://www.yicai.com/api/ajax/getbrieflist",
            {"page": 1, "pagesize": 50, "id": 0},
            page_param="page",
            max_pages=50,
            items_per_page=50
        )

        all_news.sort(key=lambda x: x.publish_ts, reverse=True)
        logger.info(f"第一财经补抓完成：共获取{len(all_news)}条历史新闻")

        if all_news:
            self.last_ts = max(n.publish_ts for n in all_news if n.publish_ts > 0)

        return all_news


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
                        except:
                            pass

                page.on('response', handle_response)

                await page.goto(url, timeout=45000)
                await page.wait_for_load_state("networkidle", timeout=20000)
                await page.wait_for_timeout(3000)

                await browser.close()

            return all_data
        except Exception as e:
            logger = __import__('logging').getLogger("news_monitor")
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

        if ts and ts <= self.last_ts:
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
                logger = __import__('logging').getLogger("news_monitor")
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
                logger = __import__('logging').getLogger("news_monitor")
                logger.warning(f"韭研公社补抓失败({url}): {str(e)[:80]}")

        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        if news_list:
            self.last_ts = max(n.publish_ts for n in news_list if n.publish_ts > 0)

        return news_list
