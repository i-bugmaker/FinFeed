#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东方财富系列股吧解析器"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup, Tag

from finfeed.config.sources import NewsSource
from finfeed.utils.time_utils import TZ_BJ, now_bj, parse_relative_time

from .base import BaseHtmlForumParser, BaseJsonForumParser
from .utils import STOCK_NAME_MAP, extract_stocks_from_text, find_time_in_element, parse_forum_time

logger = logging.getLogger("news_monitor")

EM_STOCK_RE = re.compile(r'news,(\d{6}),')
EM_STOCK_RE_ALT = re.compile(r'[=/,_](\d{6})(?:\.html)?')


class EastMoneyStockBarParser(BaseHtmlForumParser):
    """东方财富个股股吧解析器（通用，支持任何股票股吧页面）"""

    item_selectors = [
        ".listitem", ".articleh", "tr.listitem", ".normal_post",
        ".bar_list li", "ul.newlist li", ".post_item", ".list_item",
    ]
    title_selectors = ["div.title a", "a.note", "a.title", "span.l3 a", "div.title a"]
    link_selectors = ["div.title a", "a.note", "a.title", "span.l3 a", "a[href]"]
    time_selectors = ["div.update", ".time", ".update", ".pub_time", "span.l6", "span.l5", "[class*='time']", "[class*='date']"]
    intro_selectors = []

    def _parse_item(self, item: Tag, soup: BeautifulSoup) -> Optional[object]:
        link = None
        for sel in self.link_selectors:
            try:
                el = item.select_one(sel)
                if el and el.get("href"):
                    href = el.get("href", "")
                    text = el.get_text(strip=True)
                    if text and len(text) >= 4 and "javascript:" not in href:
                        link = el
                        break
            except Exception:
                continue
        if not link:
            for a in item.find_all("a", href=True):
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if text and len(text) >= 4 and ("news," in href or "/news" in href):
                    link = a
                    break
        if not link:
            return None
        href = link.get("href", "")
        if not href or "javascript:" in href:
            return None
        title = link.get_text(strip=True)
        if not title or len(title) < 4:
            parent = link.parent
            if parent:
                title = parent.get_text(strip=True)
        if not title or len(title) < 4:
            return None
        ts = 0
        for sel in self.time_selectors:
            try:
                te = item.select_one(sel)
                if te:
                    ttxt = te.get_text(strip=True)
                    ts = parse_relative_time(ttxt) or parse_forum_time(ttxt)
                    if ts > 0:
                        break
            except Exception:
                continue
        if ts <= 0:
            ts_m = re.search(r'(\d{2}-\d{2}\s+\d{2}:\d{2})', str(item))
            if ts_m:
                ts = parse_forum_time(ts_m.group(1))
        stock_code = None
        m = EM_STOCK_RE.search(href)
        if m:
            stock_code = m.group(1)
        else:
            m = EM_STOCK_RE_ALT.search(href)
            if m:
                stock_code = m.group(1)
        extra_stocks = []
        if stock_code and stock_code.startswith(("60", "688", "00", "30")):
            extra_stocks.append({
                "code": stock_code,
                "name": STOCK_NAME_MAP.get(stock_code, ""),
                "market": "sh" if stock_code.startswith(("60", "688")) else "sz"
            })
        news = self._build_news_item(
            title=title,
            url=href,
            publish_ts=ts,
            extra_stocks=extra_stocks,
        )
        return news


class EastMoneyHotBarParser(EastMoneyStockBarParser):
    """东方财富热门股吧"""
    item_selectors = [".listitem", ".articleh", ".hot_list li", ".normal_post"]


class CLSTelegraphParser(BaseJsonForumParser):
    """财联社电报 - 使用官方API /api/cache?name=telegraph"""

    data_path = ["data", "roll_data"]
    title_key = "title"
    url_key = "shareurl"
    time_key = "ctime"
    intro_key = "brief"
    time_is_timestamp = True

    async def parse(self, response: httpx.Response) -> list:
        news_list = []
        self._seen_urls.clear()
        try:
            if "text/html" in response.headers.get("content-type", ""):
                return await self._parse_html(response.text)
            data = response.json()
            items = data
            for key in self.data_path:
                if isinstance(items, dict):
                    items = items.get(key, [])
                else:
                    break
            if not isinstance(items, list):
                items = []
            for item in items:
                try:
                    if not isinstance(item, dict):
                        continue
                    title = item.get("title", "") or item.get("content", "")
                    content = item.get("content", "") or item.get("brief", "") or ""
                    title = re.sub(r'<[^>]+>', '', str(title)).strip()
                    content = re.sub(r'<[^>]+>', '', str(content)).strip()
                    if not title and content:
                        title = content[:80]
                    if not title:
                        continue
                    item_id = item.get("id", "")
                    url = item.get("shareurl", "") or f"https://www.cls.cn/detail/{item_id}"
                    if not url or url == "https://www.cls.cn/detail/":
                        continue
                    ts = item.get("ctime", 0)
                    if isinstance(ts, str):
                        ts = int(ts) if ts.isdigit() else parse_forum_time(ts)
                    extra_stocks = []
                    stocks = item.get("stock_list", []) or item.get("stocks", []) or []
                    for s in stocks:
                        if isinstance(s, dict):
                            code = s.get("StockCode", "") or s.get("code", "")
                            name = s.get("StockName", "") or s.get("name", "")
                            if code and len(code) == 6 and code.startswith(("60", "688", "00", "30")):
                                extra_stocks.append({"code": code, "name": name, "market": ""})
                    news = self._build_news_item(
                        title=title,
                        url=url,
                        publish_ts=int(ts) if ts else 0,
                        intro=content[:200],
                        extra_stocks=extra_stocks,
                    )
                    if news:
                        news_list.append(news)
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"财联社JSON解析失败，尝试HTML: {str(e)[:60]}")
            news_list = await self._parse_html(response.text)
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    async def _parse_html(self, html_text: str) -> list:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")
        items = soup.select(".telegraph-list .telegraph-item, .telegraph-content-box, .f-l-b-item")
        for item in items:
            try:
                title_elem = item.select_one(".telegraph-title, .title, h3")
                title = title_elem.get_text(strip=True) if title_elem else ""
                content_elem = item.select_one(".telegraph-content, .content, .desc")
                content = content_elem.get_text(strip=True) if content_elem else ""
                if not title and content:
                    title = content[:60]
                if not title:
                    continue
                link = item.select_one("a[href]")
                href = link.get("href", "#") if link else "#"
                ts = 0
                time_elem = item.select_one(".telegraph-time, .time, .date")
                if time_elem:
                    ttxt = time_elem.get_text(strip=True)
                    ts = parse_relative_time(ttxt) or parse_forum_time(ttxt)
                news = self._build_news_item(
                    title=title, url=href, publish_ts=ts, intro=content[:200]
                )
                if news:
                    news_list.append(news)
            except Exception:
                continue
        return news_list


class XueqiuHotParser(BaseJsonForumParser):
    """雪球热门讨论API解析器"""

    data_path = ["data"]
    title_key = "title"
    url_key = "target"
    time_key = "created_at"
    intro_key = "description"
    time_is_timestamp = True

    async def parse(self, response: httpx.Response) -> list:
        news_list = []
        self._seen_urls.clear()
        try:
            data = response.json()
            items = []
            if isinstance(data, dict):
                if "data" in data and isinstance(data["data"], list):
                    items = data["data"]
                elif "list" in data and isinstance(data["list"], list):
                    items = data["list"]
                elif "items" in data and isinstance(data["items"], list):
                    items = data["items"]
            elif isinstance(data, list):
                items = data
            for item in items:
                try:
                    if not isinstance(item, dict):
                        continue
                    target = item.get("target", {})
                    if not isinstance(target, dict):
                        target = {}
                    title = target.get("title", "") or item.get("title", "") or target.get("text_summary", "")
                    title = re.sub(r'<[^>]+>', '', str(title)).strip()
                    if not title:
                        text = item.get("text", "") or target.get("text", "")
                        text = re.sub(r'<[^>]+>', '', str(text)).strip()
                        title = text[:80]
                    if not title or len(title) < 5:
                        continue
                    tid = target.get("id", "") or item.get("id", "")
                    url = f"https://xueqiu.com/{tid}" if tid else "#"
                    ts = item.get("created_at", 0) or target.get("created_at", 0)
                    if isinstance(ts, (int, float)):
                        if ts > 10000000000:
                            ts = ts // 1000
                    else:
                        ts = parse_forum_time(str(ts))
                    desc = target.get("description", "") or item.get("description", "") or ""
                    desc = re.sub(r'<[^>]+>', '', str(desc)).strip()
                    extra_stocks = []
                    stock_info = item.get("stock", {}) or target.get("stock", {})
                    if isinstance(stock_info, dict):
                        code = stock_info.get("symbol", "").replace("SH", "").replace("SZ", "")
                        name = stock_info.get("name", "")
                        if code and len(code) == 6:
                            extra_stocks.append({"code": code, "name": name, "market": ""})
                    news = self._build_news_item(
                        title=title, url=url, publish_ts=int(ts) if ts else 0,
                        intro=desc[:200], extra_stocks=extra_stocks,
                    )
                    if news:
                        news_list.append(news)
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"雪球解析失败: {str(e)[:60]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list


class SinaStockBarParser(BaseHtmlForumParser):
    """新浪股吧（股市汇）解析器 - 适配 https://guba.sina.com.cn/"""

    item_selectors = [
        "ul.list_05 li",
        "td.alignL",
    ]
    title_selectors = ["a:not(.link_source)"]
    link_selectors = ["a:not(.link_source)"]
    time_selectors = []
    intro_selectors = []

    async def parse(self, response: httpx.Response) -> list:
        news_list = []
        self._seen_urls.clear()
        try:
            html_text = response.text
            if not html_text or len(html_text) < 500:
                raw = response.content
                for enc in ["utf-8", "gb2312", "gbk", "gb18030"]:
                    try:
                        html_text = raw.decode(enc)
                        break
                    except (UnicodeDecodeError, LookupError):
                        continue
            if self._is_empty_page(html_text):
                logger.info(f"{self.source.name}页面为空，尝试浏览器渲染")
                browser_html = await self._try_browser_render()
                if browser_html:
                    html_text = browser_html
            news_list = self._parse_html(html_text)
        except Exception as e:
            logger.warning(f"{self.source.name}解析失败: {str(e)[:80]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _parse_html(self, html_text: str) -> list:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")
        items = []
        for selector in self.item_selectors:
            try:
                found = soup.select(selector)
                valid_items = []
                for it in found:
                    if "adsDiv" in it.get("class", []):
                        continue
                    links = it.find_all("a", href=True)
                    has_thread = any("s=thread" in a.get("href", "") for a in links)
                    if has_thread:
                        valid_items.append(it)
                if len(valid_items) >= 3:
                    items = valid_items
                    break
            except Exception:
                continue
        now_ts = int(now_bj().replace(tzinfo=TZ_BJ).timestamp())
        for idx, item in enumerate(items):
            try:
                news = self._parse_sina_item(item, idx, now_ts)
                if news:
                    news_list.append(news)
            except Exception:
                continue
        return news_list

    def _parse_sina_item(self, item: Tag, idx: int, now_ts: int) -> Optional[object]:
        links = item.find_all("a", href=True)
        if not links:
            return None
        thread_link = None
        for a in links:
            href = a.get("href", "")
            if "s=thread" in href and "link_source" not in a.get("class", []):
                thread_link = a
                break
        if not thread_link:
            for a in links:
                href = a.get("href", "")
                if "thread" in href or "tid=" in href:
                    if "link_source" not in a.get("class", []):
                        thread_link = a
                        break
        if not thread_link:
            thread_link = links[-1]
        href = thread_link.get("href", "")
        if not href or "javascript:" in href or href == "#":
            return None
        title = thread_link.get_text(strip=True)
        if not title or len(title) < 4:
            return None
        title = re.sub(r'\s+', ' ', title).strip()
        time_text = ""
        for child in item.children:
            if isinstance(child, str):
                t = child.strip()
                if re.search(r'\d{1,2}:\d{2}', t):
                    time_text = t
                    break
        ts = 0
        if time_text:
            ts = parse_relative_time(time_text) or parse_forum_time(time_text)
        if ts <= 0:
            ts = find_time_in_element(item)
        if ts <= 0:
            ts = now_ts - idx * 30
        extra_stocks = []
        code_m = re.search(r'(\d{6})', href)
        if code_m:
            code = code_m.group(1)
            if code.startswith(("60", "688", "00", "30")):
                extra_stocks.append({
                    "code": code,
                    "name": STOCK_NAME_MAP.get(code, ""),
                    "market": "sh" if code.startswith(("60", "688")) else "sz"
                })
        return self._build_news_item(
            title=title, url=href, publish_ts=ts, extra_stocks=extra_stocks,
        )

    def _parse_item(self, item: Tag, soup: BeautifulSoup) -> Optional[object]:
        return None


class EastMoneyMobileGubaParser(BaseHtmlForumParser):
    """东方财富移动端个股股吧解析器
    使用 m.guba.eastmoney.com 移动端，无需浏览器渲染即可获取真实UGC帖子
    页面结构: <li class="type_0/type_20"> 包含2个<a>标签
      - 第一个<a>: 含 .name_text(作者) + .time(时间+浏览量)
      - 第二个<a>: 帖子标题/内容文本"""

    MOBILE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    item_selectors = []
    title_selectors = []
    link_selectors = []
    time_selectors = []
    intro_selectors = []

    def _get_headers(self) -> dict:
        base = dict(self.source.headers) if self.source.headers else {}
        base.update(self.MOBILE_HEADERS)
        return base

    async def parse(self, response: httpx.Response) -> list:
        news_list = []
        self._seen_urls.clear()
        try:
            html_text = response.text
            r_url = str(response.url)
            is_mobile_url = "mguba." in r_url or "/mguba/" in r_url
            if not is_mobile_url:
                code = self._extract_code_from_url(r_url) or self._extract_code_from_name()
                if code:
                    mobile_url = f"https://mguba.eastmoney.com/mguba/list/{code}"
                    try:
                        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=self._get_headers()) as _client:
                            r2 = await _client.get(mobile_url)
                            html_text = r2.text
                    except Exception:
                        pass
            if not html_text or len(html_text) < 2000:
                browser_html = await self._try_browser_render()
                if browser_html:
                    html_text = browser_html
            news_list = self._parse_html(html_text)
        except Exception as e:
            logger.warning(f"{self.source.name}解析失败: {str(e)[:80]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list

    def _extract_code_from_url(self, url: str) -> str:
        m = re.search(r'[=/,_](\d{6})', url)
        return m.group(1) if m else ""

    def _extract_code_from_name(self) -> str:
        name = self.source.name or ""
        m = re.search(r'(\d{6})', name)
        if m:
            return m.group(1)
        from .utils import STOCK_NAME_MAP
        for cname, ccode in [(v, k) for k, v in STOCK_NAME_MAP.items()]:
            if ccode in name:
                return cname
        return ""

    def _parse_html(self, html_text: str) -> list:
        news_list = []
        soup = BeautifulSoup(html_text, "lxml")
        items = soup.select("li.type_0, li.type_20")
        if not items:
            items = [li for li in soup.find_all("li") if self._is_post_li(li)]
        now_dt = now_bj()
        now_ts = int(now_dt.replace(tzinfo=TZ_BJ).timestamp())
        stock_code = self._extract_code_from_url(str(self.source.url)) or self._extract_code_from_name()
        for item in items:
            try:
                news = self._parse_mobile_item(item, now_ts, stock_code)
                if news:
                    news_list.append(news)
            except Exception:
                continue
        return news_list

    @staticmethod
    def _is_post_li(li: Tag) -> bool:
        text = li.get_text(strip=True)
        if "次浏览" not in text:
            return False
        if "更新于" not in text and "发表于" not in text:
            return False
        links = li.find_all("a", href=True)
        if not links:
            return False
        href = links[0].get("href", "")
        if not href or "javascript:" in href or href == "#":
            return False
        return True

    def _parse_mobile_item(self, item: Tag, now_ts: int, stock_code: str) -> Optional[object]:
        cls = item.get("class", [])
        if "more" in cls:
            return None
        links = item.find_all("a", href=True)
        if not links:
            return None
        meta_a = links[0]
        href = meta_a.get("href", "")
        if not href or "javascript:" in href:
            return None
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://mguba.eastmoney.com" + href
        is_homepage_style = False
        if len(links) >= 2:
            second_text = links[1].get_text(strip=True)
            if re.match(r'^\d+$', second_text):
                is_homepage_style = True
        meta_text = meta_a.get_text(strip=True)
        title = ""
        author = ""
        views_str = ""
        ts = 0
        if is_homepage_style:
            parsed = self._parse_merged_meta(meta_text, now_ts)
            if parsed:
                title = parsed["title"]
                author = parsed["author"]
                ts = parsed["ts"]
                views_str = parsed["views"]
        else:
            if len(links) < 2:
                return None
            content_a = links[1]
            alt_href = content_a.get("href", "")
            if alt_href and "javascript:" not in alt_href and not alt_href.endswith("#"):
                if alt_href.startswith("//"):
                    href = "https:" + alt_href
                elif alt_href.startswith("/"):
                    href = "https://mguba.eastmoney.com" + alt_href
                else:
                    href = alt_href
            title = content_a.get_text(strip=True)
            title = re.sub(r'\s+', ' ', title).strip()
            if not title or len(title) < 5:
                title_el = content_a.select_one(".title, .content, .text, p")
                if title_el:
                    title = title_el.get_text(strip=True)
                    title = re.sub(r'\s+', ' ', title).strip()
            name_el = meta_a.select_one(".name_text")
            if name_el:
                author = name_el.get_text(strip=True)
            time_el = meta_a.select_one("p.time, .time")
            if time_el:
                time_text = time_el.get_text(strip=True)
                views_m = re.search(r'(\d+(?:\.\d+)?万?)次浏览', time_text)
                if views_m:
                    views_str = views_m.group(0)
                    time_text = time_text.replace(views_str, "").strip()
                time_text = time_text.replace("更新于", "").replace("发表于", "").strip()
                ts = self._parse_time_text(time_text, now_ts)
            if not author or ts <= 0:
                parsed = self._parse_merged_meta(meta_text, now_ts)
                if parsed:
                    if not author:
                        author = parsed["author"]
                    if ts <= 0:
                        ts = parsed["ts"]
                    if not views_str:
                        views_str = parsed["views"]
        if not title or len(title) < 5:
            return None
        if re.match(r'^[\$]?[\u4e00-\u9fa5A-Za-z0-9]+\((?:SH|SZ|sh|sz)?\d{6}\)[\$]?$', title):
            return None
        title = title[:100]
        if ts <= 0:
            ts = now_ts
        extra_stocks = []
        if stock_code and stock_code.startswith(("60", "688", "00", "30")):
            extra_stocks.append({
                "code": stock_code,
                "name": STOCK_NAME_MAP.get(stock_code, ""),
                "market": "sh" if stock_code.startswith(("60", "688")) else "sz",
            })
        extra_stocks.extend(extract_stocks_from_text(title))
        intro_parts = []
        if author:
            intro_parts.append(f"👤{author}")
        if views_str:
            intro_parts.append(f"👁{views_str}")
        reply_el = item.select_one(".hot_reply, .reply, .comment")
        if reply_el:
            reply_text = reply_el.get_text(strip=True)
            if reply_text and "查看全部" not in reply_text:
                intro_parts.append(f"💬{reply_text[:30]}")
        elif len(links) >= 2:
            reply_text = links[1].get_text(strip=True)
            if re.match(r'^\d+$', reply_text) and int(reply_text) > 0:
                intro_parts.append(f"💬{reply_text}")
        intro = " ".join(intro_parts)
        return self._build_news_item(
            title=title,
            url=href,
            publish_ts=ts,
            intro=intro,
            extra_stocks=extra_stocks,
        )

    @staticmethod
    def _parse_time_text(time_text: str, now_ts: int) -> int:
        ts = 0
        if "今天" in time_text:
            time_text = time_text.replace("今天", "").strip()
            t_m = re.search(r'(\d{1,2}):(\d{2})', time_text)
            if t_m:
                h, mi = int(t_m.group(1)), int(t_m.group(2))
                now_dt = now_bj()
                dt = now_dt.replace(hour=h, minute=mi, second=0, microsecond=0)
                ts = int(dt.replace(tzinfo=TZ_BJ).timestamp())
        elif "昨天" in time_text:
            time_text = time_text.replace("昨天", "").strip()
            t_m = re.search(r'(\d{1,2}):(\d{2})', time_text)
            if t_m:
                h, mi = int(t_m.group(1)), int(t_m.group(2))
                now_dt = now_bj()
                dt = (now_dt - timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
                ts = int(dt.replace(tzinfo=TZ_BJ).timestamp())
        else:
            md_m = re.search(r'(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})', time_text)
            if md_m:
                mo, d, h, mi = int(md_m.group(1)), int(md_m.group(2)), int(md_m.group(3)), int(md_m.group(4))
                now_dt = now_bj()
                year = now_dt.year
                dt = datetime(year, mo, d, h, mi, tzinfo=TZ_BJ)
                if dt.timestamp() > now_ts + 3600:
                    dt = dt.replace(year=year - 1)
                ts = int(dt.timestamp())
            else:
                ts = parse_relative_time(time_text) or parse_forum_time(time_text)
        return ts

    def _parse_merged_meta(self, meta_text: str, now_ts: int) -> dict:
        result = {"author": "", "ts": 0, "views": "", "title": ""}
        m = re.match(r'^(.+?)(更新于|发表于)(.+?)(\d+(?:\.\d+)?万?)次浏览(.+)$', meta_text)
        if m:
            result["author"] = m.group(1).strip()
            time_text = m.group(3).strip()
            result["views"] = m.group(4) + "次浏览"
            result["title"] = m.group(5).strip()
            result["title"] = re.sub(r'\s+', ' ', result["title"]).strip()
            result["ts"] = self._parse_time_text(time_text, now_ts)
            return result if result["title"] else None
        return None

    def _parse_item(self, item: Tag, soup: BeautifulSoup) -> Optional[object]:
        return None


class EastMoneyHotRankParser(BaseJsonForumParser):
    """东方财富人气榜API - 个股讨论热度排名
    https://emappdata.eastmoney.com/stockrank/getAllCurrentList
    标识当前散户讨论最热的股票，含排名变化（异动信号）"""

    data_path = ["data"]
    title_key = "sc"
    url_key = "sc"
    time_key = ""
    intro_key = ""
    time_is_timestamp = False

    async def parse(self, response: httpx.Response) -> list:
        news_list = []
        self._seen_urls.clear()
        try:
            data = response.json()
            items = data.get("data", [])
            if not isinstance(items, list):
                items = []
            now_ts = int(now_bj().replace(tzinfo=TZ_BJ).timestamp())
            for item in items:
                try:
                    if not isinstance(item, dict):
                        continue
                    sc = item.get("sc", "")
                    if not sc or len(sc) < 8:
                        continue
                    market = sc[:2].lower()
                    code = sc[2:]
                    rk = item.get("rk", 0)
                    his_rc = item.get("hisRc", 0)
                    if not code.startswith(("60", "688", "00", "30")):
                        continue
                    name = STOCK_NAME_MAP.get(code, code)
                    change_str = ""
                    emoji = ""
                    if his_rc >= 5:
                        emoji = "🚀🔥"
                        change_str = f"飙升{his_rc}位！"
                    elif his_rc >= 2:
                        emoji = "📈"
                        change_str = f"上升{his_rc}位"
                    elif his_rc <= -5:
                        emoji = "📉💥"
                        change_str = f"暴跌{-his_rc}位！"
                    elif his_rc <= -2:
                        emoji = "📉"
                        change_str = f"下降{-his_rc}位"
                    else:
                        emoji = "➡️"
                        change_str = "排名稳定"
                    title = f"[人气{rk}] {name}({code}) {emoji}{change_str}"
                    guba_url = f"https://mguba.eastmoney.com/mguba/list/{code}"
                    news = self._build_news_item(
                        title=title,
                        url=guba_url,
                        publish_ts=now_ts - rk * 2,
                        intro=f"人气榜第{rk}位，{change_str} | 散户关注度风向标",
                        extra_stocks=[{"code": code, "name": name, "market": market}],
                    )
                    if news:
                        news_list.append(news)
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"东财人气榜解析失败: {str(e)[:80]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list[:30]


class EastMoneyDynamicGubaParser(BaseJsonForumParser):
    """东方财富动态全市场股吧解析器
    基于人气榜API，每次自动抓取当前Top N热门股票的股吧最新帖
    覆盖全市场，无需硬编码个股列表
    URL: https://emappdata.eastmoney.com/stockrank/getAllCurrentList (同人气榜)"""

    MOBILE_HEADERS = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    TOP_N_STOCKS = 20
    PER_STOCK_POSTS = 5
    REQUEST_DELAY = 0.35

    data_path = ["data"]
    title_key = "sc"
    url_key = "sc"
    time_key = ""
    intro_key = ""
    time_is_timestamp = False

    async def parse(self, response: httpx.Response) -> list:
        news_list = []
        self._seen_urls.clear()
        try:
            data = response.json()
            items = data.get("data", [])
            if not isinstance(items, list):
                items = []
            hot_stocks = []
            for item in items[: self.TOP_N_STOCKS]:
                try:
                    if not isinstance(item, dict):
                        continue
                    sc = item.get("sc", "")
                    if not sc or len(sc) < 8:
                        continue
                    code = sc[2:]
                    if not code.startswith(("60", "688", "00", "30")):
                        continue
                    hot_stocks.append(code)
                except Exception:
                    continue
            now_ts = int(now_bj().replace(tzinfo=TZ_BJ).timestamp())
            dummy_source = NewsSource(
                name="热门股吧",
                url="https://mguba.eastmoney.com/mguba/",
                parser_type="em_mobile_guba",
                headers=self.MOBILE_HEADERS,
            )
            mobile_parser = EastMoneyMobileGubaParser(dummy_source)
            mobile_parser._seen_urls = self._seen_urls
            async with httpx.AsyncClient(
                timeout=15, follow_redirects=True, headers=self.MOBILE_HEADERS
            ) as client:
                for idx, code in enumerate(hot_stocks):
                    try:
                        url = f"https://mguba.eastmoney.com/mguba/list/{code}"
                        mobile_parser._base_url = url
                        mobile_parser._url_stock = None
                        r = await client.get(url)
                        if r.status_code != 200 or len(r.text) < 5000:
                            continue
                        soup = BeautifulSoup(r.text, "lxml")
                        post_items = soup.select("li.type_0, li.type_20")
                        if not post_items:
                            post_items = [
                                li for li in soup.find_all("li")
                                if EastMoneyMobileGubaParser._is_post_li(li)
                            ]
                        count = 0
                        for post_item in post_items:
                            if count >= self.PER_STOCK_POSTS:
                                break
                            try:
                                news = mobile_parser._parse_mobile_item(
                                    post_item, now_ts, code
                                )
                                if news:
                                    news_list.append(news)
                                    count += 1
                            except Exception:
                                continue
                        await asyncio.sleep(self.REQUEST_DELAY)
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"动态股吧解析失败: {str(e)[:80]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list[: self.TOP_N_STOCKS * self.PER_STOCK_POSTS]


class ThsAdvisorParser(BaseHtmlForumParser):
    """同花顺投顾平台解析器（改进版，修复时间戳）"""

    item_selectors = [
        ".feed-item", ".feed_item", ".list-item", ".article-item",
        ".feed-list .item", "div.item", ".list_con li",
    ]
    title_selectors = [".feed-title", ".title", "a", "h3", "h4"]
    link_selectors = ["a[href]"]
    time_selectors = [".feed-time", ".time", ".date", ".update-time", ".pub-time", "[class*='time']", "[class*='date']"]
    intro_selectors = [".feed-content", ".content", ".desc", ".summary"]

    def _parse_item(self, item: Tag, soup: BeautifulSoup) -> Optional[object]:
        link = None
        for sel in self.link_selectors:
            try:
                found = item.select_one(sel)
                if found and found.get("href"):
                    href = found.get("href", "")
                    text = found.get_text(strip=True)
                    if text and len(text) >= 4 and "javascript" not in href:
                        link = found
                        break
            except Exception:
                continue
        if not link:
            return None
        href = link.get("href", "")
        if not href or href == "#" or "javascript:" in href:
            return None
        title = ""
        for sel in self.title_selectors:
            try:
                te = item.select_one(sel)
                if te and te != link:
                    t = te.get_text(strip=True)
                    if t and len(t) >= 4:
                        title = t
                        break
            except Exception:
                continue
        if not title:
            title = link.get_text(strip=True)
        if not title or len(title) < 4:
            return None
        ts = 0
        for sel in self.time_selectors:
            try:
                te = item.select_one(sel)
                if te:
                    ttxt = te.get_text(strip=True)
                    ts = parse_relative_time(ttxt) or parse_forum_time(ttxt)
                    if ts > 0:
                        break
            except Exception:
                continue
        if ts <= 0:
            ts = find_time_in_element(item)
        intro = ""
        for sel in self.intro_selectors:
            try:
                ie = item.select_one(sel)
                if ie:
                    itxt = ie.get_text(strip=True)
                    if itxt and itxt != title and len(itxt) > 5:
                        intro = itxt
                        break
            except Exception:
                continue
        extra_stocks = self._extract_stock_from_ths_href(href)
        return self._build_news_item(
            title=title, url=href, publish_ts=ts, intro=intro, extra_stocks=extra_stocks,
        )

    def _extract_stock_from_ths_href(self, href: str) -> list:
        stocks = []
        try:
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(href)
            params = parse_qs(parsed.query)
            for key in ["code", "stockcode", "secid", "stock_code"]:
                if key in params:
                    code = params[key][0]
                    code = re.sub(r'[^0-9]', '', code)[-6:]
                    if len(code) == 6 and code.startswith(("60", "688", "00", "30")):
                        stocks.append({
                            "code": code,
                            "name": STOCK_NAME_MAP.get(code, ""),
                            "market": "sh" if code.startswith(("60", "688")) else "sz",
                        })
        except Exception:
            pass
        code_m = re.search(r'(\d{6})', href)
        if code_m and not stocks:
            code = code_m.group(1)
            if code.startswith(("60", "688", "00", "30")):
                stocks.append({
                    "code": code,
                    "name": STOCK_NAME_MAP.get(code, ""),
                    "market": "sh" if code.startswith(("60", "688")) else "sz",
                })
        return stocks


class ThsStockBarParser(BaseHtmlForumParser):
    """同花顺股吧解析器"""

    item_selectors = [
        ".post-item", ".list-item", ".topic-list .item",
        ".bbs_list li", ".post_list li", ".thread-item",
    ]
    title_selectors = ["a.title", ".title a", "h3 a", "a"]
    link_selectors = ["a[href]"]
    time_selectors = [".time", ".date", ".post-time", ".pub-time", "[class*='time']", "[class*='date']"]
    intro_selectors = []

    def _parse_item(self, item: Tag, soup: BeautifulSoup) -> Optional[object]:
        link = None
        for a in item.find_all("a", href=True):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if text and len(text) >= 5 and ("guba" in href or "stock" in href or "/bbs/" in href or "thread" in href):
                link = a
                break
        if not link:
            link = item.find("a", href=True)
        if not link:
            return None
        href = link.get("href", "")
        if not href or "javascript:" in href or href == "#":
            return None
        title = link.get_text(strip=True)
        if not title or len(title) < 4:
            return None
        ts = 0
        for sel in self.time_selectors:
            try:
                te = item.select_one(sel)
                if te:
                    ttxt = te.get_text(strip=True)
                    ts = parse_relative_time(ttxt) or parse_forum_time(ttxt)
                    if ts > 0:
                        break
            except Exception:
                continue
        if ts <= 0:
            ts = find_time_in_element(item)
        extra_stocks = []
        code_m = re.search(r'(\d{6})', href)
        if code_m:
            code = code_m.group(1)
            if code.startswith(("60", "688", "00", "30")):
                extra_stocks.append({
                    "code": code,
                    "name": STOCK_NAME_MAP.get(code, ""),
                    "market": "sh" if code.startswith(("60", "688")) else "sz",
                })
        return self._build_news_item(
            title=title, url=href, publish_ts=ts, extra_stocks=extra_stocks,
        )


class THSNewsParser(BaseJsonForumParser):
    """同花顺财经新闻 - https://news.10jqka.com.cn/tapp/news/push/stock/"""

    data_path = ["data", "list"]
    title_key = "title"
    url_key = "url"
    time_key = "ctime"
    intro_key = "digest"
    time_is_timestamp = True

    async def parse(self, response: httpx.Response) -> list:
        news_list = []
        self._seen_urls.clear()
        try:
            text = response.text
            if text.startswith("callback("):
                text = text[text.index("(")+1:text.rindex(")")]
            import json as _json
            data = _json.loads(text) if text.startswith("callback(") else response.json()
            items = data
            for key in self.data_path:
                if isinstance(items, dict):
                    items = items.get(key, [])
                else:
                    break
            if not isinstance(items, list):
                items = []
            for item in items:
                try:
                    if not isinstance(item, dict):
                        continue
                    title = re.sub(r'<[^>]+>', '', str(item.get("title", ""))).strip()
                    if not title or len(title) < 5:
                        continue
                    url = item.get("url", "") or item.get("shareUrl", "")
                    if not url or "javascript:" in url:
                        continue
                    digest = re.sub(r'<[^>]+>', '', str(item.get("digest", ""))).strip()
                    ts = item.get("ctime", 0) or item.get("rtime", 0)
                    if isinstance(ts, str):
                        ts = int(ts) if ts.isdigit() else parse_forum_time(ts)
                    extra_stocks = []
                    stock_list = item.get("stock", []) or []
                    for s in stock_list:
                        if isinstance(s, dict):
                            code = s.get("stockCode", "")
                            name = s.get("name", "")
                            if code and len(code) == 6 and code.startswith(("60", "688", "00", "30")):
                                extra_stocks.append({"code": code, "name": name, "market": ""})
                    source = item.get("source", "")
                    intro_parts = []
                    if source:
                        intro_parts.append(f"[{source}]")
                    if digest:
                        intro_parts.append(digest)
                    news = self._build_news_item(
                        title=title,
                        url=url,
                        publish_ts=int(ts) if ts else 0,
                        intro=" ".join(intro_parts)[:200],
                        extra_stocks=extra_stocks,
                    )
                    if news:
                        news_list.append(news)
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"同花顺新闻解析失败: {str(e)[:80]}")
        news_list.sort(key=lambda x: x.publish_ts, reverse=True)
        return news_list
