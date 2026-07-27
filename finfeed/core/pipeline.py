#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻处理管道

处理流程: 解析 -> 字段清洗 -> 股票格式验证 -> 情感分析 -> 重要性评分 -> 入库
"""

import re
import logging
import time
from typing import List

from finfeed.storage.models import NewsItem
from finfeed.storage.database import db_insert_news
from finfeed.core.dedup import deduplicate
from finfeed.analysis.sentiment import analyze_sentiment_async
from finfeed.analysis.importance import compute_importance
from finfeed.analysis.text_analyzer import extract_keywords_simple

logger = logging.getLogger("news_monitor")

STOCK_CODE_PATTERN = re.compile(r'^(?:SH|SZ|BJ)?[036][0-9]{5}$|^[48][0-9]{5}$')
STOCK_CODE_RAW_PATTERN = re.compile(r'\b(60\d{4}|688\d{3}|00\d{4}|30\d{4})\b')


def _clean_title(title: str) -> str:
    if not title:
        return ""
    title = re.sub(r'\s+', ' ', title).strip()
    return title


def _clean_intro(intro: str) -> str:
    if not intro:
        return ""
    intro = re.sub(r'<[^>]+>', '', intro)
    intro = re.sub(r'\s+', ' ', intro).strip()
    if len(intro) > 500:
        intro = intro[:500] + "..."
    return intro


def _validate_stocks(raw_stocks: List[str]) -> List[str]:
    if not raw_stocks:
        return []
    valid_stocks = []
    seen = set()
    for s in raw_stocks:
        if not s:
            continue
        s = s.strip()
        if s in seen:
            continue
        if STOCK_CODE_PATTERN.match(s) or STOCK_CODE_RAW_PATTERN.match(s):
            valid_stocks.append(s)
            seen.add(s)
    return valid_stocks


def _validate_timestamp(ts: int, source: str = "") -> int:
    now_ts = int(time.time())
    if ts <= 0:
        return now_ts
    if ts > now_ts + 86400:
        return now_ts
    if ts < 946656000:
        return now_ts
    return ts


async def process_news_items(raw_items: List[NewsItem], source_name: str = "") -> List[NewsItem]:
    if not raw_items:
        return []

    processed: List[NewsItem] = []

    for item in raw_items:
        try:
            if not item.title:
                continue
            item.title = _clean_title(item.title)
            if not item.title:
                continue

            if not item.url:
                item.url = "#"

            if item.intro:
                item.intro = _clean_intro(item.intro)

            if not item.source:
                item.source = source_name

            if not item.category:
                item.category = "finance"

            item.publish_ts = _validate_timestamp(item.publish_ts, item.source)

            if item.stocks:
                item.stocks = _validate_stocks(item.stocks)

            if not item.keywords:
                try:
                    item.keywords = extract_keywords_simple(f"{item.title} {item.intro}", top_n=8)
                except Exception as e:
                    logger.debug(f"关键词提取失败 [{item.source}]: {e}")
                    item.keywords = []

            if item.sentiment == "neutral" or not item.sentiment:
                try:
                    item.sentiment = await analyze_sentiment_async(item)
                except Exception as e:
                    logger.debug(f"情感分析失败 [{item.source}]: {e}")
                    item.sentiment = "neutral"

            try:
                item.importance = compute_importance(
                    title=item.title,
                    intro=item.intro or "",
                    source=item.source or "",
                    stocks_count=len(item.stocks) if item.stocks else 0
                )
            except Exception as e:
                logger.debug(f"重要性评分失败 [{item.source}]: {e}")
                item.importance = 5.0

            processed.append(item)
        except Exception as e:
            logger.debug(f"处理新闻条目异常 [{source_name}]: {e}")
            continue

    return processed


async def process_and_store(raw_items: List[NewsItem], source_name: str = "") -> int:
    processed = await process_news_items(raw_items, source_name)
    if not processed:
        return 0

    processed = deduplicate(processed)
    inserted, count = db_insert_news(processed)

    if count > 0:
        logger.debug(f"新入库 {count} 条 [{source_name}]")

    return count
