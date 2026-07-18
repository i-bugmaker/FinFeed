#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据管道 Pipeline

将抓取 -> 解析 -> 去重 -> 分析 -> 存储 -> 通知 等环节串联起来。
支持观察者模式，可注册回调处理新新闻。
"""

import logging
from typing import Callable, Optional

from .fetcher import fetch_all_news
from .dedup import get_dedup_engine
from storage.database import db_insert_news, db_get_recent_news
from storage.models import NewsItem
from analysis.text_analyzer import extract_keywords_simple, extract_stock_codes, classify_news
from analysis.sentiment import analyze_sentiment
from analysis.importance import compute_importance

logger = logging.getLogger("news_monitor")

NewsCallback = Callable[[list[NewsItem]], None]


def _enrich_news(news_list: list[NewsItem]) -> list[NewsItem]:
    """对新闻进行信息补全：关键词、股票代码、分类、情感、重要性"""
    for n in news_list:
        text = f"{n.title} {n.intro}"
        if not n.keywords:
            n.keywords = extract_keywords_simple(text, top_n=5)
        if not n.stocks:
            stocks_info = extract_stock_codes(text)
            n.stocks = [s["code"] for s in stocks_info[:3]]
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

    async def run_cycle(self, cycle: int = 1) -> tuple[list[NewsItem], dict[str, int], int]:
        """执行一轮完整的抓取流程

        Returns:
            (所有新闻列表, 各源统计, 新增入库数量)
        """
        self._ensure_init()

        all_news, source_stats = await fetch_all_news(cycle=cycle)

        deduped_news = self._dedup_engine.batch_dedup(all_news)

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
