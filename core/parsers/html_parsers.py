#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML 页面类新闻源解析器"""

import re
import json
from datetime import datetime, timezone, timedelta

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
    """和讯网 - HTML 页面（仅从URL提取日期，页面无具体时间信息）"""

    _RE_HEXUN_URL = re.compile(r"/(\d{4})-(\d{2})-(\d{2})/(\d+)\.html")
    _RE_CLEAN_TITLE = re.compile(r"^[•●■★◆●\s]+|[•●■★◆●\s]+$")

    async def parse(self, response: httpx.Response) -> list[NewsItem]:
        news_list = []
        html_text = response.content.decode("gbk", errors="replace")
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
