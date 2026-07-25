#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据管道 Pipeline

将抓取 -> 解析 -> 去重 -> 分析 -> 存储 -> 通知 等环节串联起来。
支持观察者模式，可注册回调处理新新闻。
"""

import asyncio
import logging
from typing import Callable, Optional

from .fetcher import fetch_all_news
from .dedup import get_dedup_engine
from finfeed.storage.database import db_insert_news, db_get_recent_news
from finfeed.storage.models import NewsItem
from finfeed.analysis.text_analyzer import extract_keywords_simple, extract_stock_codes, classify_news
from finfeed.analysis.sentiment import analyze_sentiment
from finfeed.analysis.importance import compute_importance
from finfeed.config.settings import CATCH_UP_BATCH_SIZE

try:
    from finfeed.analysis.stock_names import STOCK_NAMES
except ImportError:
    STOCK_NAMES = {}

_STOCK_NAMES_SET = set(STOCK_NAMES.values()) if STOCK_NAMES else set()

logger = logging.getLogger("news_monitor")

NewsCallback = Callable[[list[NewsItem]], None]


def _format_stock_display(stock_info: dict, stock_name_map: dict) -> str:
    code = stock_info.get("code", "")
    name = stock_info.get("name", "")
    if not name and code and code in stock_name_map:
        name = stock_name_map[code]
    if name and code:
        return f"{name}({code})"
    if name:
        return name
    if code:
        if code in stock_name_map:
            return f"{stock_name_map[code]}({code})"
        return code
    return ""


def _enrich_news(news_list: list[NewsItem]) -> list[NewsItem]:
    """对新闻进行信息补全：关键词、股票代码、分类、情感、重要性"""
    for n in news_list:
        text = f"{n.title} {n.intro}"
        if not n.keywords:
            n.keywords = extract_keywords_simple(text, top_n=5)
        if not n.stocks:
            stocks_info = extract_stock_codes(text)
            stock_displays = []
            seen = set()
            for s in stocks_info[:3]:
                display = _format_stock_display(s, STOCK_NAMES)
                if display and display not in seen:
                    stock_displays.append(display)
                    seen.add(display)
            n.stocks = stock_displays
        else:
            new_stocks = []
            for s in n.stocks:
                if isinstance(s, dict):
                    display = _format_stock_display(s, STOCK_NAMES)
                    if display:
                        new_stocks.append(display)
                elif isinstance(s, str) and s:
                    if (len(s) == 6 and s.isdigit() and s.startswith(("60", "688", "00", "30"))) or s in _STOCK_NAMES_SET:
                        new_stocks.append(s)
            n.stocks = new_stocks
        if not n.category:
            n.category = classify_news(n.title, n.intro)
        if not n.sentiment or n.sentiment == "neutral":
            sentiment, _ = analyze_sentiment(n.title, n.intro)
            n.sentiment = sentiment
        if not n.importance or n.importance <= 0:
            n.importance = compute_importance(
                n.title, n.intro, n.source, len(n.stocks)
            )
    return news_list


class NewsPipeline:
    """新闻数据管道"""

    def __init__(self):
        self._callbacks: list[NewsCallback] = []
        self._dedup_engine = get_dedup_engine()
        self._initialized = False

    def _ensure_init(self):
        if not self._initialized:
            self._dedup_engine.load_from_db()
            self._initialized = True

    def register_callback(self, callback: NewsCallback):
        """注册新新闻回调"""
        self._callbacks.append(callback)

    def unregister_callback(self, callback: NewsCallback):
        """移除回调"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    async def run_cycle(self, cycle: int = 1, catch_up_mode: bool = False, sources_per_cycle: int = 0) -> tuple[list[NewsItem], dict[str, int], int]:
        """执行一轮完整的抓取流程

        Args:
            cycle: 当前轮次
            catch_up_mode: 是否为补抓模式
            sources_per_cycle: 每轮处理的源数量（0表示全部，补抓模式下使用）

        Returns:
            (所有新闻列表, 各源统计, 新增入库数量)
        """
        self._ensure_init()

        all_news, source_stats = await fetch_all_news(cycle=cycle, catch_up_mode=catch_up_mode, sources_per_cycle=sources_per_cycle)

        if not all_news:
            return all_news, source_stats, 0

        deduped_news = self._dedup_engine.batch_dedup(all_news)

        if catch_up_mode:
            enriched_news = _enrich_news(deduped_news)
            inserted_count = 0
            inserted_items = []
            for i in range(0, len(enriched_news), CATCH_UP_BATCH_SIZE):
                batch = enriched_news[i:i + CATCH_UP_BATCH_SIZE]
                batch_inserted, batch_count = db_insert_news(batch)
                inserted_count += batch_count
                inserted_items.extend(batch_inserted)
                if i + CATCH_UP_BATCH_SIZE < len(enriched_news):
                    await asyncio.sleep(0.5)
        else:
            enriched_news = _enrich_news(deduped_news)
            inserted_items, inserted_count = db_insert_news(enriched_news)

        if inserted_items and self._callbacks:
            for cb in self._callbacks:
                try:
                    cb(inserted_items)
                except Exception as e:
                    logger.warning(f"回调执行失败: {e}")

        return all_news, source_stats, inserted_count

    def get_recent_news(self, limit: int = 200, source: Optional[str] = None) -> list[NewsItem]:
        """获取最近的新闻"""
        return db_get_recent_news(limit=limit, source=source)


_global_pipeline: Optional[NewsPipeline] = None


def get_pipeline() -> NewsPipeline:
    """获取全局管道单例"""
    global _global_pipeline
    if _global_pipeline is None:
        _global_pipeline = NewsPipeline()
    return _global_pipeline
