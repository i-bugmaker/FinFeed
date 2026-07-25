#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论坛解析器工具函数"""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from bs4 import BeautifulSoup, Tag

from finfeed.utils.time_utils import now_bj, TZ_BJ, parse_relative_time

TZ_BJ = timezone(timedelta(hours=8))

STOCK_CODE_FROM_URL = re.compile(r'[=/,_](\d{6})(?:\.html)?[/?]?$')
STOCK_CODE_PATTERN = re.compile(r'\b(60\d{4}|688\d{3}|00\d{4}|30\d{4})\b')

STOCK_NAME_MAP = {}

def _load_stock_map():
    fallback = {
        "600519": "贵州茅台", "300750": "宁德时代", "002594": "比亚迪",
        "601318": "中国平安", "600036": "招商银行", "000001": "平安银行",
        "601398": "工商银行", "600030": "中信证券", "000858": "五粮液",
        "601899": "紫金矿业", "600900": "长江电力", "601012": "隆基绿能",
        "002594": "比亚迪", "300059": "东方财富", "600570": "恒生电子",
        "300308": "中际旭创", "002415": "海康威视", "002230": "科大讯飞",
        "600276": "恒瑞医药", "601857": "中国石油",
        "601606": "长城军工", "002156": "通富微电",
    }
    try:
        from finfeed.analysis.stock_names import STOCK_NAMES
        STOCK_NAME_MAP.update(STOCK_NAMES)
    except ImportError:
        pass
    STOCK_NAME_MAP.update(fallback)

_load_stock_map()


def extract_stock_from_url(url: str) -> Optional[dict]:
    if not url:
        return None
    m = STOCK_CODE_FROM_URL.search(url)
    if m:
        code = m.group(1)
        if code.startswith(("60", "688")):
            market = "sh"
        elif code.startswith(("00", "30")):
            market = "sz"
        else:
            return None
        return {
            "code": code,
            "name": STOCK_NAME_MAP.get(code, ""),
            "market": market
        }
    return None


def extract_stocks_from_text(text: str, max_count: int = 3) -> list[dict]:
    if not text:
        return []
    stocks = []
    seen = set()
    for m in STOCK_CODE_PATTERN.finditer(text):
        code = m.group(1)
        if code in seen:
            continue
        prefix = text[max(0, m.start() - 8):m.start()]
        name = None
        name_match = re.search(r'([\u4e00-\u9fa5]{2,6})\s*$', prefix)
        if name_match:
            candidate = name_match.group(1)
            if candidate not in {"公司", "股份", "集团", "股票", "证券", "代码"}:
                name = candidate
        if code.startswith(("60", "688")):
            market = "sh"
        elif code.startswith(("00", "30")):
            market = "sz"
        else:
            continue
        if not name:
            name = STOCK_NAME_MAP.get(code, "")
        stocks.append({"code": code, "name": name, "market": market})
        seen.add(code)
        if len(stocks) >= max_count:
            break
    return stocks


def merge_stocks(stock_lists: list[list[dict]]) -> list[str]:
    seen_codes = set()
    result = []
    known_names = set(STOCK_NAME_MAP.values())
    for stocks in stock_lists:
        for s in stocks:
            code = s.get("code", "")
            name = s.get("name", "")
            if code and code not in seen_codes:
                seen_codes.add(code)
                display_name = name or code
                if not name and code in STOCK_NAME_MAP:
                    display_name = STOCK_NAME_MAP[code]
                result.append(display_name)
            elif name and name in known_names and name not in seen_codes and not code:
                seen_codes.add(name)
                result.append(name)
    return result[:5]


def parse_forum_time(time_text: str, base_ts: int = 0) -> int:
    if not time_text:
        return 0
    time_text = time_text.strip()
    ts = parse_relative_time(time_text)
    if ts > 0:
        return ts
    now = now_bj()
    if base_ts > 0:
        try:
            now = datetime.fromtimestamp(base_ts, tz=TZ_BJ)
        except Exception:
            pass
    patterns = [
        (r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?", "full"),
        (r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})", "full_slash"),
        (r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})", "full_cn"),
        (r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", "md_hm"),
        (r"(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})", "md_cn_hm"),
    ]
    for pattern, ptype in patterns:
        m = re.search(pattern, time_text)
        if m:
            groups = m.groups()
            try:
                if ptype == "full":
                    year, month, day, hour, minute = int(groups[0]), int(groups[1]), int(groups[2]), int(groups[3]), int(groups[4])
                    second = int(groups[5]) if len(groups) > 5 and groups[5] else 0
                elif ptype == "full_slash":
                    year, month, day, hour, minute = int(groups[0]), int(groups[1]), int(groups[2]), int(groups[3]), int(groups[4])
                    second = 0
                elif ptype == "full_cn":
                    year, month, day, hour, minute = int(groups[0]), int(groups[1]), int(groups[2]), int(groups[3]), int(groups[4])
                    second = 0
                elif ptype == "md_hm":
                    year = now.year
                    month, day, hour, minute = int(groups[0]), int(groups[1]), int(groups[2]), int(groups[3])
                    second = 0
                elif ptype == "md_cn_hm":
                    year = now.year
                    month, day, hour, minute = int(groups[0]), int(groups[1]), int(groups[2]), int(groups[3])
                    second = 0
                else:
                    continue
                dt = datetime(year, month, day, hour, minute, second, tzinfo=TZ_BJ)
                ts = int(dt.timestamp())
                if ts > int(now.timestamp()) + 86400:
                    dt = datetime(year - 1, month, day, hour, minute, second, tzinfo=TZ_BJ)
                    ts = int(dt.timestamp())
                return ts
            except (ValueError, IndexError):
                continue
    return 0


def find_time_in_element(elem: Tag) -> int:
    if not elem:
        return 0
    selectors = [
        ".time", ".date", ".publish-time", ".pub-time", ".update-time",
        ".post-time", ".create-time", ".timestamp",
        "[class*='time']", "[class*='date']", "[class*='Time']", "[class*='Date']",
    ]
    for sel in selectors:
        try:
            time_elems = elem.select(sel)
            for te in time_elems:
                text = te.get_text(strip=True)
                ts = parse_forum_time(text)
                if ts > 0:
                    return ts
                title_attr = te.get("title", "") or te.get("data-time", "") or te.get("data-timestamp", "")
                if title_attr:
                    ts = parse_forum_time(title_attr)
                    if ts > 0:
                        return ts
        except Exception:
            continue
    all_text = elem.get_text(" ", strip=True)
    ts = parse_forum_time(all_text)
    if ts > 0:
        return ts
    return 0


def normalize_url(href: str, base_url: str) -> str:
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{href}"
    from urllib.parse import urljoin
    return urljoin(base_url, href)
