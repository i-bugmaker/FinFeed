#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""去重引擎

多级去重策略（从快到慢，从精确到模糊）：
1. URL 精确哈希去重 - O(1)，最快
2. 标题精确哈希去重 - O(1)，次快
3. SimHash 语义去重 - O(logN)，语义级去重

使用内存缓存 + 数据库兜底的双层架构。
"""

import time
from typing import Optional

from config.settings import SIMHASH_THRESHOLD, ENABLE_SEMANTIC_DEDUP, DEDUP_RECENT_DAYS
from utils.hash_utils import (
    compute_title_full_hash, compute_url_hash,
    compute_simhash, is_semantic_duplicate,
    hex_to_simhash,
)
from storage.models import NewsItem
from storage.database import get_db


class DedupEngine:
    """去重引擎

    维护内存中的哈希缓存，提供多级去重判断。
    """

    def __init__(self, enable_semantic: bool = ENABLE_SEMANTIC_DEDUP):
        self.enable_semantic = enable_semantic
        self._title_hashes: set[str] = set()
        self._url_hashes: set[str] = set()
        self._simhashes: list[int] = []
        self._loaded = False

    def load_from_db(self):
        """从数据库加载最近的哈希到内存"""
        if self._loaded:
            return
        recent_days_ts = int(time.time()) - DEDUP_RECENT_DAYS * 86400
        try:
            with get_db() as conn:
                c = conn.cursor()
                for row in c.execute(
                    "SELECT title_full_hash FROM news WHERE publish_ts >= ? AND title_full_hash IS NOT NULL",
                    (recent_days_ts,)
                ):
                    if row[0]:
                        self._title_hashes.add(row[0])
                for row in c.execute(
                    "SELECT url_hash FROM news WHERE publish_ts >= ? AND url_hash IS NOT NULL AND url_hash != ''",
                    (recent_days_ts,)
                ):
                    if row[0]:
                        self._url_hashes.add(row[0])
                if self.enable_semantic:
                    for row in c.execute(
                        "SELECT simhash FROM news WHERE publish_ts >= ? AND simhash IS NOT NULL AND simhash != ''",
                        (recent_days_ts,)
                    ):
                        if row[0]:
                            sim = hex_to_simhash(row[0]) if isinstance(row[0], str) else row[0]
                            if sim:
                                self._simhashes.append(sim)
        except Exception:
            pass
        self._loaded = True

    def is_duplicate(self, news: NewsItem) -> tuple[bool, str]:
        """判断新闻是否重复

        Returns:
            (是否重复, 去重方式: url/title/semantic/none)
        """
        if not self._loaded:
            self.load_from_db()

        url_hash = news.url_hash or compute_url_hash(news.url)
        if url_hash and url_hash in self._url_hashes:
            return True, "url"

        title_hash = news.title_full_hash or compute_title_full_hash(news.title)
        if title_hash in self._title_hashes:
            return True, "title"

        if self.enable_semantic:
            sim = news.simhash or compute_simhash(news.title + " " + news.intro)
            if sim > 0:
                for existing_sim in self._simhashes:
                    if is_semantic_duplicate(sim, existing_sim, SIMHASH_THRESHOLD):
                        return True, "semantic"

        return False, "none"

    def add(self, news: NewsItem):
        """将新闻加入去重缓存"""
        title_hash = news.title_full_hash or compute_title_full_hash(news.title)
        self._title_hashes.add(title_hash)
        news.title_full_hash = title_hash

        url_hash = news.url_hash or compute_url_hash(news.url)
        if url_hash:
            self._url_hashes.add(url_hash)
            news.url_hash = url_hash

        if self.enable_semantic:
            sim = news.simhash or compute_simhash(news.title + " " + news.intro)
            if sim > 0:
                self._simhashes.append(sim)
                news.simhash = sim

    def batch_dedup(self, news_list: list[NewsItem]) -> list[NewsItem]:
        """批量去重，返回去重后的新闻列表"""
        if not self._loaded:
            self.load_from_db()

        result = []
        batch_seen_titles = set()
        batch_seen_urls = set()
        batch_simhashes = []

        for news in news_list:
            url_hash = news.url_hash or compute_url_hash(news.url)
            title_hash = news.title_full_hash or compute_title_full_hash(news.title)

            if url_hash and (url_hash in self._url_hashes or url_hash in batch_seen_urls):
                continue

            if title_hash in self._title_hashes or title_hash in batch_seen_titles:
                continue

            if self.enable_semantic:
                sim = news.simhash or compute_simhash(news.title + " " + news.intro)
                if sim > 0:
                    is_dup = False
                    for existing_sim in self._simhashes + batch_simhashes:
                        if is_semantic_duplicate(sim, existing_sim, SIMHASH_THRESHOLD):
                            is_dup = True
                            break
                    if is_dup:
                        continue
                    batch_simhashes.append(sim)
                    news.simhash = sim

            batch_seen_titles.add(title_hash)
            if url_hash:
                batch_seen_urls.add(url_hash)
            news.title_full_hash = title_hash
            news.url_hash = url_hash
            result.append(news)

        for news in result:
            self._title_hashes.add(news.title_full_hash)
            if news.url_hash:
                self._url_hashes.add(news.url_hash)
            if news.simhash:
                self._simhashes.append(news.simhash)

        return result


_global_dedup_engine: Optional[DedupEngine] = None


def get_dedup_engine() -> DedupEngine:
    """获取全局去重引擎单例"""
    global _global_dedup_engine
    if _global_dedup_engine is None:
        _global_dedup_engine = DedupEngine()
    return _global_dedup_engine
