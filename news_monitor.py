#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FinFeed 实时新闻监控脚本
===========================
独立运行的新闻抓取脚本，支持12个主流财经信息源的实时监控、SQLite持久化、JSON/CSV导出和Web仪表盘。

用法:
    python news_monitor.py                     # 启动实时监控（默认每30秒抓取一次）
    python news_monitor.py --interval 60       # 自定义抓取间隔（秒）
    python news_monitor.py --once              # 只抓取一次后退出
    python news_monitor.py --export json       # 导出所有新闻为JSON
    python news_monitor.py --export csv        # 导出所有新闻为CSV
    python news_monitor.py --export json --start 2024-01-01 --end 2024-01-31
"""

import os
import re
import sys
import csv
import time
import json
import html
import random
import hashlib
import asyncio
import sqlite3
import logging
import argparse
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from collections import Counter
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.console import Console, Group
from rich import box

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("news_monitor")

# Rich 控制台
console = Console()

# ============================================================
# 时间工具函数
# ============================================================
TZ_BJ = timezone(timedelta(hours=8))


def now_bj() -> datetime:
    """获取当前北京时间（无时区信息的 datetime）"""
    return datetime.now(TZ_BJ).replace(tzinfo=None)


def ts_from_bj_str(s: str) -> int:
    """将北京时间字符串转换为 Unix 时间戳
    
    支持格式:
      - 'YYYY-MM-DD HH:MM:SS' (北京时间)
      - RSS RFC-822 格式: 'Wed, 04 Jun 2026 10:47:03 GMT'
      - 含时区偏移: '2026-06-04T17:47:03+08:00'
    """
    if not s:
        return 0
    s = s.strip()
    # 尝试标准北京时间格式
    try:
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        return int(dt.replace(tzinfo=TZ_BJ).timestamp())
    except (ValueError, TypeError):
        pass
    # 尝试 ISO 8601 格式 (含 T 分隔符和时区)
    try:
        s_iso = s.replace("T", " ")
        dt = datetime.strptime(s_iso[:19], "%Y-%m-%d %H:%M:%S")
        return int(dt.replace(tzinfo=TZ_BJ).timestamp())
    except (ValueError, TypeError):
        pass
    # 尝试 RSS RFC-822 格式
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%d %b %Y %H:%M:%S %z",
    ):
        try:
            dt = datetime.strptime(s.strip(), fmt)
            return int(dt.timestamp())
        except (ValueError, TypeError):
            continue
    # 尝试手动解析 RFC-822 (如 "Wed, 04 Jun 2026 10:47:03 +0800")
    try:
        m = re.match(
            r"(?:\w+,\s+)?(\d{1,2})\s+(\w+)\s+(\d{4})\s+(\d{2}):(\d{2}):(\d{2})\s*(.*)",
            s,
        )
        if m:
            day, mon_str, year, hour, minute, sec, tz_str = m.groups()
            months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
                      "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
            mon = months.get(mon_str, 0)
            if mon:
                dt = datetime(int(year), mon, int(day), int(hour), int(minute), int(sec))
                # 根据时区偏移调整
                if tz_str and tz_str not in ("GMT", "UTC"):
                    tz_m = re.match(r"([+-]?)(\d{2}):?(\d{2})", tz_str)
                    if tz_m:
                        sign = -1 if tz_m.group(1) == "-" else 1
                        off_h, off_m = int(tz_m.group(2)), int(tz_m.group(3))
                        dt = dt - timedelta(hours=sign * off_h, minutes=sign * off_m)
                    dt = dt.replace(tzinfo=timezone.utc)
                    return int(dt.timestamp())
                else:
                    dt = dt.replace(tzinfo=timezone.utc)
                    return int(dt.timestamp())
    except (ValueError, TypeError, AttributeError):
        pass
    return 0


def bj_str_from_ts(ts: int) -> str:
    """将 Unix 时间戳转换为北京时间字符串"""
    if not ts:
        return now_bj().strftime("%Y-%m-%d %H:%M:%S")
    return datetime.fromtimestamp(ts, tz=TZ_BJ).strftime("%Y-%m-%d %H:%M:%S")


def parse_relative_time(time_str: str) -> int:
    """解析相对时间字符串，如 '5分钟前', '2小时前', '昨天 23:05', '今天 22:58'"""
    now = now_bj()
    if not time_str:
        return 0
    try:
        if "分钟前" in time_str:
            m = re.search(r"(\d+)", time_str)
            if m:
                return int((now - timedelta(minutes=int(m.group(1)))).replace(tzinfo=TZ_BJ).timestamp())
        elif "小时前" in time_str:
            m = re.search(r"(\d+)", time_str)
            if m:
                return int((now - timedelta(hours=int(m.group(1)))).replace(tzinfo=TZ_BJ).timestamp())
        elif "天前" in time_str:
            m = re.search(r"(\d+)", time_str)
            if m:
                return int((now - timedelta(days=int(m.group(1)))).replace(tzinfo=TZ_BJ).timestamp())
        elif time_str.startswith("昨天"):
            m = re.search(r"(\d{1,2}):(\d{2})", time_str)
            if m:
                hour, minute = int(m.group(1)), int(m.group(2))
                dt = (now - timedelta(days=1)).replace(hour=hour, minute=minute, second=0)
                return int(dt.replace(tzinfo=TZ_BJ).timestamp())
        elif time_str.startswith("今天"):
            m = re.search(r"(\d{1,2}):(\d{2})", time_str)
            if m:
                hour, minute = int(m.group(1)), int(m.group(2))
                dt = now.replace(hour=hour, minute=minute, second=0)
                return int(dt.replace(tzinfo=TZ_BJ).timestamp())
        elif "前天" in time_str:
            return int((now - timedelta(days=2)).replace(hour=0, minute=0, second=0, tzinfo=TZ_BJ).timestamp())
        m = re.match(r"^(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})$", time_str)
        if m:
            month, day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            dt = now.replace(month=month, day=day, hour=hour, minute=minute, second=0)
            ts = int(dt.replace(tzinfo=TZ_BJ).timestamp())
            if ts > int(now.replace(tzinfo=TZ_BJ).timestamp()):
                dt = dt.replace(year=dt.year - 1)
            return int(dt.replace(tzinfo=TZ_BJ).timestamp())
    except (ValueError, AttributeError):
        pass
    return 0


# ============================================================
# 去重工具函数
# ============================================================
def compute_simhash(text: str) -> int:
    """计算文本的 SimHash 指纹（用于近似去重）"""
    if not text:
        return 0
    ngrams = []
    n = 3
    for i in range(len(text) - n + 1):
        ngrams.append(text[i : i + n])
    if not ngrams:
        ngrams = [text]
    v = [0] * 64
    for ng in ngrams:
        ng_hash = int(hashlib.md5(ng.encode("utf-8")).hexdigest(), 16)
        for i in range(64):
            if ng_hash & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1
    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= 1 << i
    return fingerprint


def hamming_distance(hash1: int, hash2: int) -> int:
    """计算两个 SimHash 的汉明距离"""
    x = hash1 ^ hash2
    dist = 0
    while x:
        dist += 1
        x &= x - 1
    return dist


def compute_title_full_hash(title: str) -> str:
    """计算标题的完整 MD5 哈希（用于精确去重）"""
    return hashlib.md5(title.encode("utf-8")).hexdigest()


def compute_url_hash(url: str) -> str:
    """计算 URL 的 MD5 哈希（用于精确去重）"""
    if not url or url == "#":
        return ""
    return hashlib.md5(url.encode("utf-8")).hexdigest()


# ============================================================
# 速率限制配置
# ============================================================
SOURCE_RATE_LIMITS: dict[str, float] = {}
_last_source_req: dict[str, float] = {}
_rate_blocked_until: dict[str, float] = {}

# ============================================================
# 新闻源配置
# ============================================================
FINANCE_NEWS_SOURCES = [
    {
        "name": "新浪财经",
        "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&num=15",
        "headers": {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn/",
            "Accept": "application/json",
        },
    },
    {
        "name": "财联社",
        "url": "https://www.cls.cn/v1/roll/get_roll_list",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.cls.cn/telegraph",
            "Accept": "application/json",
        },
    },
    {
        "name": "同花顺",
        "url": "https://news.10jqka.com.cn/tapp/news/push/stock",
        "headers": {
            "User-Agent": "Mozilla/5.0",
            "Referer": "http://news.10jqka.com.cn/",
            "Accept": "application/json",
        },
        "params": {"page": 1, "tag": "", "type": "all"},
    },
    {
        "name": "东方财富",
        "url": "https://np-listapi.eastmoney.com/comm/web/getFastNewsList",
        "headers": {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://kuaixun.eastmoney.com/",
            "Accept": "application/json",
        },
        "params": {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": 20,
        },
    },
    {
        "name": "雅虎财经",
        "url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,AAPL,MSFT&region=US&lang=en-US",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
    },
    {
        "name": "21经济网",
        "url": "https://api.21jingji.com/timestream/getListweb?page=1",
        "headers": {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.21jingji.com/",
            "Accept": "application/json",
        },
    },
    {
        "name": "华尔街见闻",
        "url": "https://api-one.wallstcn.com/apiv1/content/information-flow?channel=global-channel&accept=article&limit=30",
        "headers": {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://wallstreetcn.com/",
            "Accept": "application/json",
        },
    },
    {
        "name": "雪球",
        "url": "https://xueqiu.com/u/5124430882",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://xueqiu.com/",
            "Accept": "text/html",
        },
    },
    {
        "name": "金十数据",
        "url": "https://www.jin10.com/flash_newest.js",
        "headers": {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.jin10.com/",
            "Accept": "*/*",
        },
    },
    {
        "name": "格隆汇",
        "url": "https://www.gelonghui.com/news/",
        "headers": {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.gelonghui.com/",
            "Accept": "text/html",
        },
    },
    {
        "name": "法布财经",
        "url": "https://www.fastbull.com/cn/express-news",
        "headers": {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.fastbull.com/",
            "Accept": "text/html",
        },
    },
    {
        "name": "企查查",
        "url": "https://www.qcc.com/api/home/getNewsFlash?firstRankIndex=1&lastRankIndex=0&lastRankTime=&pageSize=30",
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.qcc.com/",
            "Accept": "application/json",
        },
    },
]

# 不同源的特殊配置
SOURCE_TIMEOUTS = {
    "雪球": 12.0,
    "金十数据": 10.0,
    "格隆汇": 12.0,
    "法布财经": 12.0,
}

SOURCE_SKIP_REQ_TRACE = {"21经济网"}

# 各来源上次抓取的最新时间戳（用于增量更新）
source_last_ts: dict[str, int] = {s["name"]: 0 for s in FINANCE_NEWS_SOURCES}


# ============================================================
# 新闻抓取核心函数
# ============================================================
async def fetch_news_from_source(source: dict) -> list:
    """从指定新闻源抓取新闻"""
    news_list = []
    source_name = source["name"]
    last_ts = source_last_ts.get(source_name, 0)
    timeout = SOURCE_TIMEOUTS.get(source_name, 8.0)

    # 冷却检查
    blocked_until = _rate_blocked_until.get(source_name, 0)
    if blocked_until > time.time():
        remaining = int(blocked_until - time.time())
        logger.debug(f"{source_name} 仍在冷却中，跳过（剩余 {remaining}s）")
        return news_list

    try:
        # 速率限制
        min_interval = SOURCE_RATE_LIMITS.get(source_name, 0)
        if min_interval > 0:
            elapsed = time.time() - _last_source_req.get(source_name, 0)
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)

        ssl_ctx = True

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=ssl_ctx) as client:
            kwargs = {"url": source["url"], "headers": source["headers"]}
            method = source.get("method", "GET")
            if "params" in source and source_name not in SOURCE_SKIP_REQ_TRACE:
                params_dict = dict(source["params"])
                if method == "GET":
                    kwargs["params"] = params_dict
                    kwargs["params"]["req_trace"] = str(int(time.time() * 1000))
                else:
                    kwargs["data"] = params_dict
            elif "params" in source and source_name in SOURCE_SKIP_REQ_TRACE:
                kwargs["params"] = dict(source["params"])

            # 财联社需要签名认证
            if source_name == "财联社":
                cls_params = {
                    "app": "CailianpressWeb",
                    "os": "web",
                    "sv": "8.4.6",
                    "rn": "20",
                    "last_time": str(int(last_ts if last_ts > 0 else time.time())),
                }
                qs = urlencode(sorted(cls_params.items()))
                cls_params["sign"] = hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()
                kwargs["params"] = cls_params

            if method == "POST":
                response = await client.post(**kwargs)
            else:
                response = await client.get(**kwargs)

            if min_interval > 0:
                _last_source_req[source_name] = time.time()

            if response.status_code == 429:
                retry_after_str = (response.headers.get("Retry-After") or "").strip()
                retry_after = int(retry_after_str) if retry_after_str.isdigit() else 60
                logger.warning(f"{source_name} 触发速率限制 (429)，冷却 {retry_after}s")
                _rate_blocked_until[source_name] = time.time() + retry_after + 30
                return news_list

            if response.status_code != 200:
                logger.warning(f"获取{source_name}失败：HTTP {response.status_code}")
                return news_list

            # --- 各来源解析逻辑 ---

            # 21经济网 - JSON
            if source_name == "21经济网":
                data = response.json()
                for item in data.get("list", []):
                    title = (item.get("title") or "").strip()
                    if not title:
                        continue
                    time_str = item.get("inputtime", "") or ""
                    if time_str and len(time_str) == 16:
                        time_str += ":00"
                    ts = ts_from_bj_str(time_str)
                    if ts <= last_ts:
                        continue
                    pt = bj_str_from_ts(ts) if ts else now_bj().strftime("%Y-%m-%d %H:%M:%S")
                    url = item.get("url", "") or "#"
                    intro = re.sub(r"\s+", " ", (item.get("content") or "").strip())[:150]
                    news_list.append({
                        "title": title[:80], "url": url, "source": source_name,
                        "publish_time": pt, "publish_ts": ts, "intro": intro,
                    })

            # 华尔街见闻 - JSON
            elif source_name == "华尔街见闻":
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
                    if ts <= last_ts:
                        continue
                    pt = bj_str_from_ts(ts) if ts else now_bj().strftime("%Y-%m-%d %H:%M:%S")
                    url = resource.get("uri", "")
                    if url and not url.startswith("http"):
                        url = f"https://wallstreetcn.com{url}"
                    news_list.append({
                        "title": title[:80], "url": url or "#", "source": source_name,
                        "publish_time": pt, "publish_ts": ts, "intro": (resource.get("content_short", "") or "")[:150],
                    })

            # 雪球 - HTML
            elif source_name == "雪球":
                soup = BeautifulSoup(response.text, "html.parser")
                articles = soup.select(".timeline__item, .status-item, [class*='timeline'] li, [class*='status'] li")
                if not articles:
                    articles = soup.find_all("li")
                for article in articles:
                    content_elem = article.select_one(".content, [class*='content'], p")
                    time_elem = article.select_one(".time, [class*='time'], [class*='date']")
                    title_elem = article.select_one(".title, [class*='title']")
                    if not content_elem:
                        continue
                    content = content_elem.get_text(strip=True)[:80]
                    if len(content) < 4:
                        continue
                    ts, pt = 0, now_bj().strftime("%Y-%m-%d %H:%M:%S")
                    if time_elem:
                        time_text = time_elem.get_text(strip=True)
                        if time_text and re.match(r"\d{4}-\d{2}-\d{2}", time_text):
                            try:
                                dt = datetime.strptime(time_text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                                ts = int(dt.timestamp())
                                pt = bj_str_from_ts(ts)
                            except ValueError:
                                pass
                    if ts <= last_ts:
                        continue
                    link = "#"
                    a_tag = article.find("a", href=True)
                    if a_tag:
                        link = a_tag["href"]
                        if not link.startswith("http"):
                            link = f"https://xueqiu.com{link}"
                    title = title_elem.get_text(strip=True) if title_elem else content[:60]
                    news_list.append({
                        "title": title[:80], "url": link, "source": source_name,
                        "publish_time": pt, "publish_ts": ts, "intro": content[:150],
                    })

            # 金十数据 - JavaScript变量
            elif source_name == "金十数据":
                text = re.sub(r"^var\s+newest\s*=\s*", "", response.text).rstrip(";").strip()
                if text:
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
                        title_raw = re.sub(r"<[^>]+>", "", title_raw)
                        m = re.match(r"^【([^】]*)】(.*)$", title_raw)
                        title, desc = (m.group(1).strip(), m.group(2).strip()) if m else (title_raw, "")
                        if not title:
                            continue
                        ts = ts_from_bj_str(item.get("time", ""))
                        if ts <= last_ts:
                            continue
                        pt = bj_str_from_ts(ts) if ts else now_bj().strftime("%Y-%m-%d %H:%M:%S")
                        news_list.append({
                            "title": title[:80],
                            "url": f"https://flash.jin10.com/detail/{item.get('id', '')}",
                            "source": source_name, "publish_time": pt, "publish_ts": ts, "intro": desc[:150] if desc else "",
                        })

            # 格隆汇 - HTML
            elif source_name == "格隆汇":
                soup = BeautifulSoup(response.text, "html.parser")
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
                    if ts <= last_ts:
                        continue
                    pt = bj_str_from_ts(ts) if ts else now_bj().strftime("%Y-%m-%d %H:%M:%S")
                    news_list.append({
                        "title": title[:80], "url": url or "#", "source": source_name,
                        "publish_time": pt, "publish_ts": ts, "intro": info[:150] if info else "",
                    })

            # 法布财经 - HTML
            elif source_name == "法布财经":
                soup = BeautifulSoup(response.text, "html.parser")
                _fb_seen = set()  # 单次抓取内去重
                for article in soup.select(".news-list"):
                    title_elem = article.select_one(".title_name")
                    if not title_elem:
                        continue
                    title_raw = title_elem.get_text(strip=True)
                    m = re.search(r"【([^】]+)】", title_raw)
                    title = m.group(1).strip() if m else title_raw
                    if len(title) < 4:
                        continue
                    if title in _fb_seen:
                        continue
                    _fb_seen.add(title)
                    date_attr = article.get("data-date", "")
                    ts = int(date_attr) // 1000 if date_attr.isdigit() else 0
                    if ts <= last_ts:
                        continue
                    pt = bj_str_from_ts(ts) if ts else now_bj().strftime("%Y-%m-%d %H:%M:%S")
                    news_list.append({
                        "title": title[:80], "url": "#", "source": source_name,
                        "publish_time": pt, "publish_ts": ts, "intro": "",
                    })

            # 雅虎财经 - RSS XML
            elif source_name == "雅虎财经":
                soup = BeautifulSoup(response.text, "xml")
                for item in soup.find_all("item"):
                    title_tag = item.find("title")
                    link_tag = item.find("link")
                    pub_date_tag = item.find("pubDate")
                    desc_tag = item.find("description")
                    title = (title_tag.text if title_tag else "无标题").strip()
                    link = link_tag.text if link_tag else "#"
                    ts, pt = 0, now_bj().strftime("%Y-%m-%d %H:%M:%S")
                    pub_date = pub_date_tag.text if pub_date_tag else ""
                    try:
                        if pub_date:
                            pub_clean = pub_date.strip()
                            if pub_clean.endswith(" GMT"):
                                pub_clean = pub_clean[:-4] + " +0000"
                            dt = datetime.strptime(pub_clean, "%a, %d %b %Y %H:%M:%S %z")
                            ts = int(dt.timestamp())
                            pt = bj_str_from_ts(ts)
                    except (ValueError, TypeError):
                        pass
                    if ts <= last_ts:
                        continue
                    intro = ""
                    if desc_tag and desc_tag.text:
                        desc_soup = BeautifulSoup(desc_tag.text, "lxml")
                        intro = desc_soup.get_text(strip=True)[:150]
                    news_list.append({
                        "title": title, "url": link, "source": source_name,
                        "publish_time": pt, "publish_ts": ts, "intro": intro,
                    })

            # 企查查 - JSON API (实时快讯)
            elif source_name == "企查查":
                data = response.json()
                if not isinstance(data, list):
                    logger.warning(f"企查查 API 返回非数组: {str(data)[:100]}")
                    data = []
                for item in data:
                    ts_ms = item.get("publish_time", 0)
                    ts = ts_ms // 1000 if ts_ms > 1e12 else (int(ts_ms) if ts_ms else 0)
                    if ts <= last_ts:
                        continue
                    pt = bj_str_from_ts(ts) if ts else now_bj().strftime("%Y-%m-%d %H:%M:%S")
                    fd = item.get("feed_data") or {}
                    links = fd.get("links") or []
                    title = links[0].get("title", "").strip() if links else ""
                    if not title:
                        # 无链接时从 content 提取标题（取前 60 字符）
                        title = re.sub(r"<[^>]+>", "", fd.get("content", "")).strip()[:60]
                    if not title:
                        continue
                    # 优先用 news_id 构造正式链接，回退从 share URL 提取 id
                    news_id = item.get("news_id", "")
                    if not news_id and links:
                        m = re.search(r'[?&]id=([a-f0-9]+)', links[0].get("url", ""))
                        news_id = m.group(1) if m else ""
                    url = f"https://news.qcc.com/postnews/{news_id}.html?pageSource=dynamic" if news_id else (links[0].get("url", "#") if links else "#")
                    intro = re.sub(r"<[^>]+>", "", fd.get("content", "")).strip()
                    intro = re.sub(r"\s+", " ", intro)[:150]
                    news_list.append({
                        "title": title[:80], "url": url or "#", "source": source_name,
                        "publish_time": pt, "publish_ts": ts, "intro": intro,
                    })

            else:
                # JSON 源解析（新浪财经、财联社、同花顺、东方财富）
                data = response.json()

                if source_name == "新浪财经":
                    for a in data.get("result", {}).get("data", []):
                        ctime = a.get("ctime", "")
                        ts = int(ctime) if ctime and str(ctime).isdigit() else 0
                        if ts <= last_ts:
                            continue
                        pt = bj_str_from_ts(ts)
                        news_list.append({
                            "title": (a.get("title") or "无标题").strip(),
                            "url": a.get("url", "#"),
                            "source": source_name,
                            "publish_time": pt,
                            "publish_ts": ts,
                            "intro": (a.get("intro", "") or "")[:150],
                        })

                elif source_name == "财联社":
                    for a in data.get("data", {}).get("roll_data", []):
                        ctime = a.get("ctime", "")
                        ts = int(ctime) if ctime and str(ctime).isdigit() else 0
                        if ts <= last_ts:
                            continue
                        pt = bj_str_from_ts(ts)
                        title = (a.get("title") or a.get("brief", "") or "无标题").strip()[:50]
                        news_list.append({
                            "title": title or "无标题",
                            "url": f"https://www.cls.cn/detail/{a.get('id', '')}" if a.get("id") else (a.get("shareurl", "#")),
                            "source": source_name,
                            "publish_time": pt,
                            "publish_ts": ts,
                            "intro": (a.get("brief", "") or a.get("content", "") or "")[:150],
                        })

                elif source_name == "同花顺":
                    for a in data.get("data", {}).get("list", []):
                        ctime = a.get("ctime", "")
                        ts = int(ctime) if ctime and str(ctime).isdigit() else 0
                        if ts <= last_ts:
                            continue
                        pt = bj_str_from_ts(ts)
                        share_url = a.get("shareUrl", "")
                        url = "#"
                        if share_url and "/share/" in share_url:
                            m = re.search(r"/share/(\d+)/?", share_url)
                            if m:
                                aid = m.group(1)
                                date_str = bj_str_from_ts(ts)[:10].replace("-", "")
                                url = f"https://news.10jqka.com.cn/{date_str}/c{aid}.shtml"
                            else:
                                url = share_url
                        elif share_url:
                            url = share_url
                        news_list.append({
                            "title": (a.get("title") or "无标题").strip(),
                            "url": url,
                            "source": source_name,
                            "publish_time": pt,
                            "publish_ts": ts,
                            "intro": (a.get("digest", "") or a.get("short", "") or "")[:150],
                        })

                elif source_name == "东方财富":
                    for a in data.get("data", {}).get("fastNewsList", []):
                        st = a.get("showTime", "")
                        ts = ts_from_bj_str(st)
                        if ts <= last_ts:
                            continue
                        pt = st[:19] if st else now_bj().strftime("%Y-%m-%d %H:%M:%S")
                        code = a.get("code", "")
                        news_list.append({
                            "title": (a.get("title") or "无标题").strip(),
                            "url": f"https://finance.eastmoney.com/a/{code}.html" if code else "#",
                            "source": source_name,
                            "publish_time": pt,
                            "publish_ts": ts,
                            "intro": (a.get("summary", "") or "")[:150],
                        })

    except httpx.ConnectTimeout:
        logger.warning(f"获取{source_name}失败：连接超时")
    except httpx.ConnectError as e:
        logger.warning(f"获取{source_name}失败：连接错误 - {str(e)[:60]}")
    except Exception as e:
        logger.warning(f"获取{source_name}失败：{str(e)[:100]}")

    if news_list:
        timestamps = [n["publish_ts"] for n in news_list if n.get("publish_ts", 0) > 0]
        if timestamps:
            source_last_ts[source_name] = max(timestamps)

    return news_list


# ============================================================
# 数据库操作
# ============================================================
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_monitor.db")

_db_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5)
        _db_conn.row_factory = sqlite3.Row
    return _db_conn


@contextmanager
def get_db():
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                url TEXT,
                source TEXT NOT NULL,
                publish_time TEXT,
                publish_ts INTEGER DEFAULT 0,
                intro TEXT,
                title_hash TEXT UNIQUE,
                created_at TEXT,
                title_full_hash TEXT,
                url_hash TEXT,
                simhash TEXT,
                dedup_group INTEGER DEFAULT 0
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_publish_ts ON news(publish_ts DESC, id DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_created ON news(created_at ASC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_title_full_hash ON news(title_full_hash)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_url_hash ON news(url_hash)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_simhash ON news(simhash)")
        conn.commit()
        yield conn
    except Exception:
        conn.rollback()
        raise


def db_insert_news(news_list: list) -> tuple[list, int]:
    """插入新闻到数据库（自动去重）"""
    if not news_list:
        return [], 0
    with get_db() as conn:
        c = conn.cursor()
        new_hashes = []
        inserted = 0
        c.execute("SELECT MAX(dedup_group) FROM news")
        max_group = c.fetchone()[0] or 0
        seven_days_ago = int(time.time()) - 7 * 86400

        for n in news_list:
            title = n["title"]
            url = n.get("url", "#")

            # 标题精确去重
            title_full_hash = compute_title_full_hash(title)
            c.execute("SELECT id FROM news WHERE title_full_hash = ? LIMIT 1", (title_full_hash,))
            if c.fetchone():
                logger.debug(f"去重[标题精确]: {title[:40]}")
                continue

            # URL精确去重
            url_hash = compute_url_hash(url)
            if url_hash:
                c.execute("SELECT id FROM news WHERE url_hash = ? LIMIT 1", (url_hash,))
                if c.fetchone():
                    logger.debug(f"去重[URL精确]: {title[:40]}")
                    continue

            # SimHash 近似去重
            simhash_val = compute_simhash(title)
            simhash_hex = f"{simhash_val:016x}"
            dedup_group = 0
            c.execute(
                "SELECT simhash, dedup_group FROM news WHERE simhash IS NOT NULL AND simhash != '' AND dedup_group > 0 AND publish_ts > ? ORDER BY publish_ts DESC LIMIT 500",
                (seven_days_ago,),
            )
            for ex in c.fetchall():
                ex_simhash = int(ex["simhash"], 16) if isinstance(ex["simhash"], str) else ex["simhash"]
                if hamming_distance(simhash_val, ex_simhash) <= 10:
                    dedup_group = ex["dedup_group"]
                    break

            if dedup_group == 0:
                max_group += 1
                dedup_group = max_group

            title_hash = f"{n['title'][:30]}|{n['source']}"
            try:
                c.execute(
                    """INSERT OR IGNORE INTO news (title, url, source, publish_time, publish_ts, intro, title_hash, created_at, title_full_hash, url_hash, simhash, dedup_group)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (title, url, n["source"], n["publish_time"], n.get("publish_ts", 0), n["intro"],
                     title_hash, now_bj().strftime("%Y-%m-%d %H:%M:%S"), title_full_hash, url_hash, simhash_hex, dedup_group),
                )
                if c.rowcount > 0:
                    new_hashes.append(title_hash)
                    inserted += 1
            except sqlite3.IntegrityError:
                pass

        conn.commit()
    return new_hashes, inserted


def db_get_recent_news(limit=200):
    """从数据库获取最近的新闻用于显示"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT title, url, source, publish_time, publish_ts, intro FROM news ORDER BY publish_ts DESC, id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in c.fetchall()]


def db_get_all_for_export(start_date=None, end_date=None):
    """获取所有新闻用于导出"""
    with get_db() as conn:
        c = conn.cursor()
        query = "SELECT title, url, source, publish_time, publish_ts, intro FROM news WHERE 1=1"
        params = []
        if start_date:
            query += " AND publish_time >= ?"
            params.append(start_date)
        if end_date:
            query += " AND publish_time <= ?"
            params.append(end_date + " 23:59:59")
        query += " ORDER BY publish_ts DESC, id DESC"
        c.execute(query, params)
        return [dict(row) for row in c.fetchall()]


# ============================================================
# 批量抓取所有来源
# ============================================================
async def fetch_all_news() -> tuple[list, dict]:
    """并发抓取所有新闻源"""
    semaphore = asyncio.Semaphore(12)

    async def _fetch_with_sem(source):
        async with semaphore:
            return await fetch_news_from_source(source)

    tasks = [asyncio.create_task(_fetch_with_sem(s)) for s in FINANCE_NEWS_SOURCES]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_news, source_stats = [], {}
    _seen_keys = set()  # 跨来源去重：(title, source) 组合
    for s, r in zip(FINANCE_NEWS_SOURCES, results):
        name = s["name"]
        if isinstance(r, list):
            for item in r:
                key = (item["title"], item["source"])
                if key in _seen_keys:
                    continue
                _seen_keys.add(key)
                all_news.append(item)
            source_stats[name] = len(r)
        else:
            source_stats[name] = 0
            logger.warning(f"抓取{name}异常: {r}")

    all_news.sort(key=lambda x: x.get("publish_time", ""), reverse=True)
    return all_news, source_stats


# ============================================================
# 导出功能
# ============================================================
def export_to_json(output_path: str, start_date=None, end_date=None):
    """导出新闻为 JSON 文件"""
    news = db_get_all_for_export(start_date, end_date)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(news, f, ensure_ascii=False, indent=2)
    logger.info(f"已导出 {len(news)} 条新闻到: {output_path}")
    return len(news)


def export_to_csv(output_path: str, start_date=None, end_date=None):
    """导出新闻为 CSV 文件（支持 Excel 直接打开）"""
    news = db_get_all_for_export(start_date, end_date)
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["标题", "链接", "来源", "发布时间", "时间戳", "简介"])
        for n in news:
            writer.writerow([n["title"], n["url"], n["source"], n["publish_time"], n["publish_ts"], n["intro"]])
    logger.info(f"已导出 {len(news)} 条新闻到: {output_path}")
    return len(news)


# ============================================================
# CLI 界面渲染
# ============================================================
def _make_link(url: str, text: str) -> str:
    """生成终端可点击的超链接（OSC 8 协议）"""
    if not url or url == "#":
        return text
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"


# 来源颜色配置
SOURCE_COLORS = {
    "新浪财经": "#55aaff",
    "财联社": "#ff3b30",
    "同花顺": "red",
    "东方财富": "#ff9500",
    "雅虎财经": "#aaaaaa",
    "21经济网": "#0078ff",
    "华尔街见闻": "#00d4ff",
    "雪球": "#0066ff",
    "金十数据": "#ff9500",
    "格隆汇": "#68af00",
    "法布财经": "#00a0e9",
    "企查查": "magenta",
}


def _build_news_table(news_list: list, max_rows: int = 0) -> Table:
    """构建新闻表格（圆角边框样式）

    每条数据严格占一行，标题超长时自动截断（ellipsis），
    表格宽度随终端窗口自适应，带圆角边框和序号列。
    """
    total = len(news_list)
    table = Table(
        title=f"📰 财经资讯 ({total}条)",
        box=box.ROUNDED,
        border_style="cyan",
        show_header=True,
        header_style="bold white",
        show_lines=False,
        pad_edge=True,
        expand=True,
    )
    table.add_column("序号", style="yellow", width=4, justify="center", no_wrap=True)
    table.add_column("标题 (Ctrl+点击跳转)", style="cyan", ratio=1, no_wrap=True, overflow="ellipsis")
    table.add_column("来源", style="magenta", width=10, no_wrap=True)
    table.add_column("时间", style="dim", width=19, no_wrap=True)

    shown = 0
    for n in news_list:
        if max_rows and shown >= max_rows:
            break
        pub_time = n.get("publish_time", "")
        source = n.get("source", "")
        title = n.get("title", "")
        url = n.get("url", "#")

        source_color = SOURCE_COLORS.get(source, "#aaaaaa")
        source_display = f"[{source_color}]{source}[/]"

        if url and url != "#":
            title_display = f"[link={url}]{title}[/link]"
        else:
            title_display = title

        table.add_row(str(shown + 1), title_display, source_display, pub_time)
        shown += 1

    return table


def _build_display(news_list: list, cycle: int, total_news: int, new_count: int,
                    source_stats: dict, interval: int, status: str,
                    table: Table | None = None) -> Group:
    """构建完整的终端布局（Group 模式：顶部状态栏 + 表格 + 底部栏）

    当传入预构建的 table 时，只重建 header（轻量级时钟刷新），
    避免每次时钟更新都重建整个表格导致事件循环阻塞。
    """
    now_str = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    stats_parts = []
    for name, count in source_stats.items():
        if count > 0:
            stats_parts.append(f"{name}:{count}")
        else:
            stats_parts.append(f"[dim]{name}:0[/dim]")
    stats_line = " ".join(stats_parts)

    header_text = (
        f"[bold white] FinFeed 实时监控[/]"
        f" [dim]│[/] {now_str}"
        f" [dim]│[/] 第{cycle}轮"
        f" [dim]│[/] 库内{total_news}条"
        f"{' [green]│ +' + str(new_count) + '条新[/]' if new_count > 0 else ''}"
        f" [dim]│[/] 间隔{interval}s"
        f" [dim]│[/] {status}"
    )
    status_bar = Panel(
        Text.from_markup(header_text + "\n " + stats_line),
        border_style="cyan",
        box=box.SIMPLE,
    )

    # 新闻表格：使用预构建的 table 或按需重建
    if table is None:
        term_height = console.size.height
        max_rows = max(10, term_height - 12)
        table = _build_news_table(news_list, max_rows=max_rows)

    footer = Panel(
        f"[dim]按 Ctrl+C 退出 │ 网页仪表盘: [cyan]http://localhost:{_web_port}[/][/]",
        border_style="dim",
        box=box.SIMPLE,
    )

    return Group(status_bar, table, footer)


def _jitter_interval(base: int) -> float:
    """带抖动的等待间隔：基础间隔 ± 30% 随机浮动，避免固定节奏被封 IP"""
    lo = base * 0.7
    hi = base * 1.3
    return random.uniform(lo, hi)


# ============================================================
# Web 服务器
# ============================================================
_web_port = 8866

_web_state = {
    "news": [],
    "stats": {},
    "cycle": 0,
    "total": 0,
    "new_count": 0,
    "status": "启动中",
    "sources": [],
    "last_update": "",
    "server_ts": time.time(),
}

_WEB_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FinFeed 实时监控</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:'Cascadia Code','Consolas','Microsoft YaHei',monospace;padding:16px;font-size:14px}
.header{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:16px}
.header-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.header h1{color:#58a6ff;font-size:18px;margin-bottom:8px}
.header h1 span{color:#8b949e;font-size:13px;font-weight:normal;margin-left:12px}
.export-bar{display:flex;gap:8px;align-items:center;flex-shrink:0}
.export-bar .btn{background:#238636;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;transition:background .2s;white-space:nowrap}
.export-bar .btn:hover{background:#2ea043}
.export-bar select{background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:5px 8px;border-radius:6px;font-size:13px}
.stats{display:flex;gap:20px;flex-wrap:wrap;color:#8b949e;font-size:13px}
.stats .item{display:flex;align-items:center;gap:4px}
.stats .val{color:#58a6ff;font-weight:bold}
.stats .new{color:#3fb950}
.filters{margin:12px 0;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.filters span{color:#8b949e;font-size:12px}
.filters button{background:#21262d;color:#8b949e;border:1px solid #30363d;padding:3px 10px;border-radius:12px;cursor:pointer;font-size:12px;transition:all .2s;outline:none}
.filters button:hover{border-color:#58a6ff;color:#58a6ff;background:#1c2333}
.filters button.active{background:#1f6feb;color:#fff;border-color:#1f6feb;box-shadow:0 0 8px rgba(31,111,235,.4)}
.filters button:active{transform:scale(.95)}
table{width:100%;border-collapse:collapse}
thead th{background:#161b22;color:#f0f6fc;padding:10px 12px;text-align:left;position:sticky;top:0;border-bottom:2px solid #30363d;font-weight:600}
tbody tr{border-bottom:1px solid #21262d;transition:background .15s}
tbody tr:hover{background:#161b22}
tbody td{padding:8px 12px;vertical-align:middle;white-space:nowrap}
.col-time{color:#8b949e;width:170px;white-space:nowrap;font-size:13px}
.col-source{width:90px;font-size:13px}
.col-source span{background:#21262d;padding:2px 8px;border-radius:10px;font-size:12px}
.col-title{max-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;width:100%}
.col-title a{color:#c9d1d9;text-decoration:none;transition:color .15s}
.col-title a:hover{color:#58a6ff}
.empty{text-align:center;padding:60px;color:#484f58}
@media(max-width:768px){
  body{padding:8px;font-size:13px}
  .header{padding:12px}
  .header-top{flex-direction:column;gap:8px}
  .header h1{font-size:15px}
  .header h1 span{display:block;margin:4px 0 0 0}
  .stats{gap:10px;font-size:12px}
  .export-bar{width:100%;justify-content:flex-end}
  .filters{gap:6px}
  .filters button{padding:4px 8px;font-size:11px}
  table{font-size:12px}
  thead th{padding:8px 6px;font-size:12px}
  tbody td{padding:6px;white-space:nowrap}
  .col-time{width:auto;font-size:11px}
  .col-source{width:60px;font-size:11px}
  .col-source span{padding:1px 5px;font-size:10px}
  .col-title{font-size:12px}
  .col-title a{font-size:12px}
}
@media(max-width:480px){
  .stats .item{font-size:11px}
  thead th:nth-child(1),.col-time{display:none}
  .col-source{width:50px}
}
</style>
</head>
<body>
<div class="header">
<div class="header-top">
<h1>&#9608; FinFeed<span id="update-time"></span></h1>
<div class="export-bar">
<select id="export-format"><option value="json">JSON</option><option value="csv">CSV</option></select>
<button class="btn" onclick="doExport()">&#128229; 导出</button>
</div>
</div>
<div class="stats">
<div class="item">&#128337; 第 <span class="val" id="cycle">0</span> 轮</div>
<div class="item">&#128202; 库内 <span class="val" id="total">0</span> 条</div>
<div class="item new">&#10133; 新增 <span class="val" id="new-count">0</span> 条</div>
<div class="item">&#9881; <span id="status">启动中</span></div>
</div>
</div>
<div class="filters" id="filters"><span>筛选来源:</span><button class="active" data-source="all">全部</button></div>
<table>
<thead><tr><th style="width:170px">时间</th><th style="width:90px">来源</th><th>标题</th></tr></thead>
<tbody id="news-body"><tr><td colspan="3" class="empty">正在加载...</td></tr></tbody>
</table>
<script>
let allNews=[], activeSource='all', serverOffset=0;
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function truncate(s,n){return s.length>n?s.slice(0,n)+'...':s}
function pad(n){return n<10?'0'+n:n}
function bjNow(){
  // 基于服务器偏移量计算北京时间，每秒本地刷新
  const now=new Date(Date.now()+serverOffset);
  return now.getFullYear()+'-'+pad(now.getMonth()+1)+'-'+pad(now.getDate())+' '+pad(now.getHours())+':'+pad(now.getMinutes())+':'+pad(now.getSeconds())
}
// 每秒刷新顶部时钟（不依赖 API 轮询）
setInterval(()=>{document.getElementById('update-time').textContent=bjNow()},1000);
async function load(){
  try{
    const r=await fetch('/api/news');
    const d=await r.json();
    // 计算服务器时间与本地时间的偏移量
    if(d.server_ts){serverOffset=(d.server_ts*1000)-Date.now()}
    document.getElementById('cycle').textContent=d.cycle;
    document.getElementById('total').textContent=d.total;
    document.getElementById('new-count').textContent=d.new_count;
    document.getElementById('status').textContent=d.status;
    document.getElementById('update-time').textContent=bjNow();
    allNews=d.news||[];
    const sources=[...new Set(allNews.map(n=>n.source))];
    const fc=document.getElementById('filters');
    const cur=fc.querySelector('.active');
    const curSrc=cur?cur.dataset.source:'all';
    let btns='<span>\u7B5B\u9009\u6765\u6E90:</span><button class="'+(curSrc==='all'?'active':'')+'" data-source="all">\u5168\u90E8</button>';
    sources.forEach(s=>{btns+='<button class="'+(curSrc===s?'active':'')+'" data-source="'+esc(s)+'">'+esc(s)+'</button>'});
    fc.innerHTML=btns;
    fc.querySelectorAll('button').forEach(b=>b.onclick=()=>{activeSource=b.dataset.source;fc.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');render()});
    render();
  }catch(e){console.error(e)}
}
function render(){
  const tb=document.getElementById('news-body');
  const filtered=activeSource==='all'?allNews:allNews.filter(n=>n.source===activeSource);
  if(!filtered.length){tb.innerHTML='<tr><td colspan="3" class="empty">暂无数据</td></tr>';return}
  tb.innerHTML=filtered.slice(0,300).map(n=>{
    const link=n.url&&n.url!=='#'&&n.url.startsWith('http')?'<a href="'+esc(n.url)+'" target="_blank" rel="noopener noreferrer">'+esc(truncate(n.title,80))+'</a>':esc(truncate(n.title,80));
    return '<tr><td class="col-time">'+esc(n.publish_time||'')+'</td><td class="col-source"><span>'+esc(n.source)+'</span></td><td class="col-title">'+link+'</td></tr>'
  }).join('');
}
load();setInterval(load,5000);
function doExport(){
  const fmt=document.getElementById('export-format').value;
  window.open('/api/export?format='+fmt,'_blank');
}
</script>
</body>
</html>"""


class _WebHandler(BaseHTTPRequestHandler):
    """Web 仪表盘 HTTP 请求处理器"""

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            data = _WEB_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path.startswith("/api/news"):
            state = dict(_web_state)
            state["server_ts"] = time.time()  # 每次请求都返回精确服务器时间
            data = json.dumps(state, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path.startswith("/api/export"):
            # 解析查询参数
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            fmt = qs.get("format", ["json"])[0]
            start = qs.get("start", [None])[0]
            end = qs.get("end", [None])[0]
            news = db_get_all_for_export(start, end)
            ts_str = now_bj().strftime("%Y%m%d_%H%M%S")
            if fmt == "csv":
                import io
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(["标题", "链接", "来源", "发布时间", "时间戳", "简介"])
                for n in news:
                    w.writerow([n["title"], n["url"], n["source"], n["publish_time"], n["publish_ts"], n["intro"]])
                data = buf.getvalue().encode("utf-8-sig")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="finfeed_news_{ts_str}.csv"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                data = json.dumps(news, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="finfeed_news_{ts_str}.json"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        else:
            self.send_error(404)

    def log_message(self, fmt, *args):
        # 静默日志，不干扰 CLI 输出
        pass


def _start_web_server(port: int = 8866):
    """在后台线程启动 Web 仪表盘服务"""
    server = HTTPServer(("0.0.0.0", port), _WebHandler)
    server.daemon_threads = True
    t = threading.Thread(target=server.serve_forever, daemon=True, name="web-dashboard")
    t.start()
    return server


def _update_web_state(news, stats, cycle, total, new_count, status):
    """更新 Web 仪表盘共享状态（线程安全）"""
    _web_state["news"] = news[:300]
    _web_state["stats"] = stats
    _web_state["cycle"] = cycle
    _web_state["total"] = total
    _web_state["new_count"] = new_count
    _web_state["status"] = status
    _web_state["sources"] = list(stats.keys())
    _web_state["last_update"] = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    _web_state["server_ts"] = time.time()


# ============================================================
# 主监控循环
# ============================================================
async def monitor_loop(interval: int = 5, once: bool = False):
    """
    主监控循环：定期抓取所有新闻源并持久化，实时刷新终端显示

    Args:
        interval: 抓取间隔（秒），默认5秒
        once: 是否只抓取一次
    """
    cycle = 0
    all_collected_news: list[dict] = []  # 累积所有本轮会话抓到的新闻
    source_stats: dict[str, int] = {s["name"]: 0 for s in FINANCE_NEWS_SOURCES}
    total_in_db = 0
    last_new_count = 0

    # 先统计数据库中已有的新闻数
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM news")
            total_in_db = c.fetchone()[0]
    except Exception:
        pass

    if once:
        # 单次模式：不启动 Live，直接打印结果
        all_news, source_stats = await fetch_all_news()
        new_hashes, inserted = db_insert_news(all_news)
        all_collected_news.extend(all_news)
        all_collected_news.sort(key=lambda x: x.get("publish_ts", 0), reverse=True)
        total_in_db += inserted
        last_new_count = inserted

        console.print()
        console.print(Panel(
            f"[bold white on blue] FinFeed 单次抓取完成 [/]"
            f" [cyan]{now_bj().strftime('%Y-%m-%d %H:%M:%S')}[/]"
            f" | 抓取 {len(all_news)} 条 | 新增入库 {inserted} 条 | 库内共 {total_in_db} 条",
            border_style="bright_blue",
        ))
        console.print()
        table = _build_news_table(all_collected_news)
        console.print(table)
        return

    # 持续监控模式
    # screen=True: 使用终端备用缓冲区，消除重绘闪烁
    # refresh_per_second=1: 低帧率避免过度刷新
    # 只在数据变化时调用 live.update()，进一步减少无谓重绘
    with Live(
        _build_display(all_collected_news, 0, total_in_db, 0, source_stats, interval, "启动中..."),
        console=console,
        refresh_per_second=2,
        screen=True,
    ) as live:
        # 缓存上次构建的表格，时钟更新时只重建 header，避免事件循环阻塞
        _cached_table: Table | None = None
        _last_table_key = ""

        def _rebuild_table_if_needed(news, force=False):
            """只在新闻列表变化时重建表格（轻量判断）"""
            nonlocal _cached_table, _last_table_key
            key = f"{len(news)}|{news[0]['title'] if news else ''}"
            if force or key != _last_table_key:
                _last_table_key = key
                term_height = console.size.height
                max_rows = max(10, term_height - 12)
                _cached_table = _build_news_table(news, max_rows=max_rows)
            return _cached_table

        def _update_display(news, cyc, total, new_ct, stats, itv, st, force=False, rebuild_table=False):
            table = _rebuild_table_if_needed(news, force=rebuild_table) if rebuild_table else _cached_table
            live.update(_build_display(news, cyc, total, new_ct, stats, itv, st, table=table))

        while True:
            cycle += 1
            _update_display(
                all_collected_news, cycle, total_in_db, 0,
                source_stats, interval, "抓取中...", rebuild_table=True
            )

            # 抓取期间每 0.3s 刷新时钟，只重建 header（表格不变）
            fetch_task = asyncio.create_task(fetch_all_news())
            while not fetch_task.done():
                await asyncio.sleep(0.3)
                _update_display(
                    all_collected_news, cycle, total_in_db, last_new_count,
                    source_stats, interval, "抓取中...", force=True
                )
            all_news, source_stats = fetch_task.result()
            new_hashes, inserted = db_insert_news(all_news)

            # 将新抓取的新闻优雅合并：新条目插入到列表头部，保持时间排序
            if all_news:
                seen_titles = {n["title"] for n in all_collected_news}
                new_items = [n for n in all_news if n["title"] not in seen_titles]
                if new_items:
                    new_items.sort(key=lambda x: x.get("publish_ts", 0), reverse=True)
                    all_collected_news = new_items + [n for n in all_collected_news if n["title"] not in {x["title"] for x in new_items}]
            total_in_db += inserted
            last_new_count = inserted

            # 更新状态：等待中（每秒刷新时钟）
            wait_sec = _jitter_interval(interval)
            status = f"新增{inserted}条" if inserted > 0 else "无新内容"
            _update_web_state(
                all_collected_news, source_stats, cycle, total_in_db,
                last_new_count, f"{status} | {wait_sec:.1f}s后下一轮"
            )

            # 等待期间每秒刷新时钟显示（只重建 header）
            wait_end = time.time() + wait_sec
            # 数据变化后重建一次表格
            _update_display(
                all_collected_news, cycle, total_in_db, last_new_count,
                source_stats, interval, f"{status} | {wait_sec:.0f}s后下一轮",
                force=True, rebuild_table=True
            )
            while time.time() < wait_end:
                await asyncio.sleep(0.5)
                remaining = max(0, wait_end - time.time())
                st = f"{status} | {remaining:.0f}s后下一轮"
                _update_display(
                    all_collected_news, cycle, total_in_db, last_new_count,
                    source_stats, interval, st, force=True
                )


# ============================================================
# 命令行入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="FinFeed 实时新闻监控脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python news_monitor.py                      # 启动实时监控
  python news_monitor.py --interval 60        # 每60秒抓取一次
  python news_monitor.py --once               # 只抓取一次
  python news_monitor.py --export json        # 导出为JSON
  python news_monitor.py --export csv         # 导出为CSV
  python news_monitor.py --export json --start 2024-01-01 --end 2024-01-31
        """
    )
    parser.add_argument("--port", type=int, default=8866, help="Web 仪表盘端口（默认 8866）")
    parser.add_argument("--interval", type=int, default=5, help="抓取间隔（秒），默认5")
    parser.add_argument("--once", action="store_true", help="只抓取一次后退出")
    parser.add_argument("--export", choices=["json", "csv"], help="导出格式 (json 或 csv)")
    parser.add_argument("--output", "-o", help="导出文件路径（默认自动生成）")
    parser.add_argument("--start", help="导出起始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", help="导出截止日期 (YYYY-MM-DD)")

    args = parser.parse_args()

    # 初始化数据库
    with get_db():
        pass

    if args.export:
        # 导出模式
        timestamp = now_bj().strftime("%Y%m%d_%H%M%S")
        if args.output:
            output_path = args.output
        else:
            ext = "json" if args.export == "json" else "csv"
            output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"news_export_{timestamp}.{ext}")

        if args.export == "json":
            count = export_to_json(output_path, args.start, args.end)
        else:
            count = export_to_csv(output_path, args.start, args.end)

        print(f"\n导出完成: {count} 条新闻已保存到 {output_path}")
    else:
        # 监控模式
        web_server = None
        try:
            # 启动 Web 仪表盘
            global _web_port
            _web_port = args.port
            web_server = _start_web_server(port=args.port)
            asyncio.run(monitor_loop(interval=args.interval, once=args.once))
        except KeyboardInterrupt:
            logger.info("\n用户中断，正在退出...")
            logger.info(f"数据已保存在: {DB_PATH}")
            print(f"\n监控已停止。所有数据已持久化到: {DB_PATH}")
        finally:
            if web_server:
                web_server.shutdown()


if __name__ == "__main__":
    main()
