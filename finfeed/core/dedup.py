#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多级新闻去重引擎

四级去重漏斗：
  L1 URL精确去重 - 同一URL直接跳过
  L2 标题标准化哈希 - 去除标点/来源前缀后精确匹配
  L3 SimHash语义去重 - 汉明距离<=3判定为同事件
  L4 时间+关键词兜底 - 10分钟内+关键词/股票重合度>=60%判定重复

策略：发现重复不直接丢弃，而是合并元数据
  - 保留高优先级来源的主记录
  - 合并其他源的信息到主记录（摘要更全则更新、时间更早则更新、股票/关键词取并集）
  - duplicate_sources 记录所有报道源
"""

import time
import logging
import threading
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional, Set
from collections import deque

from finfeed.storage.models import NewsItem
from finfeed.config.settings import (
    SIMHASH_THRESHOLD, DEDUP_TIME_WINDOW, DEDUP_KEYWORD_OVERLAP,
    DEDUP_SLIDING_WINDOW_SIZE, DEDUP_SLIDING_WINDOW_TTL,
    get_source_priority, is_forum_source,
)
from finfeed.utils.hash_utils import (
    compute_normalized_title_hash, compute_simhash, simhash_to_hex,
    hex_to_simhash, hamming_distance,
)

logger = logging.getLogger("news_monitor")


@dataclass
class CachedEntry:
    """滑动窗口缓存条目"""
    news_id: int
    title_hash: str
    simhash: int
    publish_ts: int
    source: str
    priority: int
    keywords: Set[str]
    stocks: Set[str]
    url: str = ""


class DedupEngine:
    """多级去重引擎（单例，线程安全）"""

    _instance: Optional["DedupEngine"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        # 滑动窗口：保留最近的新闻条目用于快速比对
        self._window: deque[CachedEntry] = deque(maxlen=DEDUP_SLIDING_WINDOW_SIZE)
        # 索引：title_hash -> entry（用于L2快速命中）
        self._title_hash_index: Dict[str, CachedEntry] = {}
        # simhash列表（用于L3线性扫描，规模可控）
        self._simhash_list: List[Tuple[int, CachedEntry]] = []
        # URL索引（用于L1快速命中）
        self._url_index: Dict[str, CachedEntry] = {}
        self._window_lock = threading.RLock()
        # 统计
        self._stats = {"l1_hits": 0, "l2_hits": 0, "l3_hits": 0, "l4_hits": 0, "new_items": 0}

    def _prune_window(self):
        """清理过期的缓存条目"""
        now = int(time.time())
        cutoff = now - DEDUP_SLIDING_WINDOW_TTL
        while self._window and self._window[0].publish_ts < cutoff:
            entry = self._window.popleft()
            self._title_hash_index.pop(entry.title_hash, None)
            if entry.url:
                self._url_index.pop(entry.url, None)
            # 从simhash_list中移除（重建一次，避免线性删除的复杂度）
        # 当窗口较大时，定期重建simhash_list
        if len(self._simhash_list) > DEDUP_SLIDING_WINDOW_SIZE * 2:
            self._rebuild_simhash_list()

    def _rebuild_simhash_list(self):
        """重建simhash列表（从window中重新构建）"""
        self._simhash_list = [(e.simhash, e) for e in self._window if e.simhash != 0]

    def _compute_overlap(self, set1: Set[str], set2: Set[str]) -> float:
        """计算两个集合的Jaccard重合度"""
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0

    def _merge_items(self, existing: NewsItem, new: NewsItem) -> NewsItem:
        """合并重复新闻：保留高优先级源，合并其他源的信息
        返回更新后的existing（主记录）
        """
        # 记录重复源
        existing_sources = set(existing.duplicate_sources) if existing.duplicate_sources else set()
        existing_sources.add(existing.source)
        existing_sources.add(new.source)
        existing.duplicate_sources = list(existing_sources)
        existing.duplicate_count = len(existing.duplicate_sources) - 1  # 减去主源自己

        # 如果新条目摘要更长/更全，更新摘要
        if new.intro and len(new.intro) > len(existing.intro or ""):
            existing.intro = new.intro

        # 如果新条目发布时间更早，更新为最早时间
        if new.publish_ts > 0 and (existing.publish_ts == 0 or new.publish_ts < existing.publish_ts):
            existing.publish_ts = new.publish_ts
            if new.publish_time:
                existing.publish_time = new.publish_time

        # 合并stocks（取并集）
        existing_stocks = set(existing.stocks) if existing.stocks else set()
        new_stocks = set(new.stocks) if new.stocks else set()
        existing.stocks = list(existing_stocks | new_stocks)

        # 合并keywords（取并集）
        existing_kw = set(existing.keywords) if existing.keywords else set()
        new_kw = set(new.keywords) if new.keywords else set()
        existing.keywords = list(existing_kw | new_kw)

        # 如果新条目重要性更高，更新
        if new.importance > existing.importance:
            existing.importance = new.importance

        # 标记需要在数据库中更新
        existing._needs_update = True  # type: ignore
        existing._merge_with_id = existing.id  # type: ignore
        return existing

    def _check_duplicate(self, item: NewsItem) -> Tuple[Optional[CachedEntry], int, str]:
        """检查单条新闻是否重复
        Returns:
            (匹配到的缓存条目或None, 匹配层级1-4或0, 说明信息)
        """
        # 论坛类源只做L1 URL精确去重，不做跨源语义去重
        is_forum = is_forum_source(item.source)

        # L1: URL精确去重（非#的URL才检查）
        if item.url and item.url != "#":
            if item.url in self._url_index:
                return self._url_index[item.url], 1, "L1-URL精确匹配"

        if is_forum:
            return None, 0, ""

        # L2: 标题标准化哈希
        if item.title_hash and item.title_hash in self._title_hash_index:
            return self._title_hash_index[item.title_hash], 2, "L2-标题标准化匹配"

        # L3: SimHash语义匹配
        item_simhash = hex_to_simhash(item.content_simhash) if item.content_simhash else 0
        if item_simhash != 0:
            min_dist = 999
            best_entry = None
            for sh, entry in self._simhash_list:
                # 时间差过大直接跳过
                if abs(entry.publish_ts - item.publish_ts) > DEDUP_TIME_WINDOW * 3:
                    continue
                dist = hamming_distance(item_simhash, sh)
                if dist <= SIMHASH_THRESHOLD and dist < min_dist:
                    min_dist = dist
                    best_entry = entry
                    if dist == 0:
                        break
            if best_entry is not None:
                return best_entry, 3, f"L3-SimHash语义匹配(距离={min_dist})"

        # L4: 时间+关键词兜底
        if item.publish_ts > 0:
            item_keywords = set(item.keywords) if item.keywords else set()
            item_stocks = set(item.stocks) if item.stocks else set()
            best_entry = None
            best_overlap = 0.0
            for entry in self._window:
                if abs(entry.publish_ts - item.publish_ts) > DEDUP_TIME_WINDOW:
                    continue
                kw_overlap = self._compute_overlap(item_keywords, entry.keywords)
                stock_overlap = self._compute_overlap(item_stocks, entry.stocks)
                overlap = max(kw_overlap, stock_overlap)
                if overlap >= DEDUP_KEYWORD_OVERLAP and overlap > best_overlap:
                    best_overlap = overlap
                    best_entry = entry
            if best_entry is not None:
                return best_entry, 4, f"L4-时间+关键词兜底(重合度={best_overlap:.2f})"

        return None, 0, ""

    def deduplicate_batch(self, news_list: List[NewsItem]) -> Tuple[List[NewsItem], List[Tuple[NewsItem, NewsItem]], Dict[str, int]]:
        """批量去重处理
        Returns:
            (new_items需要新增的条目, merge_pairs需要合并更新的(新条目,主条目)对, 统计信息)
        """
        with self._window_lock:
            self._prune_window()

            new_items: List[NewsItem] = []
            merge_pairs: List[Tuple[NewsItem, NewsItem]] = []
            stats = {"total": len(news_list), "l1": 0, "l2": 0, "l3": 0, "l4": 0, "new": 0, "merged": 0, "duplicate": 0}

            # 先按优先级排序，高优先级先处理作为主记录
            sorted_items = sorted(news_list, key=lambda x: -get_source_priority(x.source))

            for item in sorted_items:
                # 计算哈希
                if not item.title_hash and item.title:
                    item.title_hash = compute_normalized_title_hash(item.title)
                if not item.content_simhash and item.title:
                    content = f"{item.title} {item.intro[:200]}" if item.intro else item.title
                    item.content_simhash = simhash_to_hex(compute_simhash(content))

                matched_entry, level, reason = self._check_duplicate(item)

                if matched_entry is not None:
                    stats[f"l{level}"] += 1
                    stats["duplicate"] += 1
                    # 查找对应的主记录（在new_items中或已标记合并）
                    # 简化处理：直接作为需要合并的条目返回
                    # 创建一个临时主记录占位，实际合并在数据库层完成
                    primary = NewsItem(
                        title="", id=matched_entry.news_id, source=matched_entry.source,
                        publish_ts=matched_entry.publish_ts
                    )
                    merge_pairs.append((item, primary))
                    logger.debug(f"去重{reason}: [{item.source}] {item.title[:40]}... -> 主记录ID={matched_entry.news_id} [{matched_entry.source}]")
                else:
                    # 新条目，加入窗口
                    stats["new"] += 1
                    new_items.append(item)
                    entry = CachedEntry(
                        news_id=0,  # 入库后更新
                        title_hash=item.title_hash,
                        simhash=hex_to_simhash(item.content_simhash) if item.content_simhash else 0,
                        publish_ts=item.publish_ts,
                        source=item.source,
                        priority=get_source_priority(item.source),
                        keywords=set(item.keywords) if item.keywords else set(),
                        stocks=set(item.stocks) if item.stocks else set(),
                        url=item.url or "",
                    )
                    if item.url and item.url != "#":
                        self._url_index[item.url] = entry
                    if item.title_hash:
                        self._title_hash_index[item.title_hash] = entry
                    if entry.simhash != 0:
                        self._simhash_list.append((entry.simhash, entry))
                    self._window.append(entry)

            self._stats["l1_hits"] += stats["l1"]
            self._stats["l2_hits"] += stats["l2"]
            self._stats["l3_hits"] += stats["l3"]
            self._stats["l4_hits"] += stats["l4"]
            self._stats["new_items"] += stats["new"]

            return new_items, merge_pairs, stats

    def update_after_insert(self, inserted_items: List[NewsItem]):
        """入库成功后，更新缓存中的news_id
        数据库插入成功后调用，把临时entry的news_id更新为真实ID
        """
        with self._window_lock:
            # 构建title_hash到item的映射
            id_map: Dict[str, NewsItem] = {}
            url_map: Dict[str, NewsItem] = {}
            for item in inserted_items:
                if item.title_hash:
                    id_map[item.title_hash] = item
                if item.url and item.url != "#":
                    url_map[item.url] = item
            # 更新window中的条目
            for entry in self._window:
                if entry.news_id == 0:
                    if entry.title_hash in id_map:
                        entry.news_id = id_map[entry.title_hash].id or 0
                    elif entry.url and entry.url in url_map:
                        entry.news_id = url_map[entry.url].id or 0

    def get_stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def reset_stats(self):
        self._stats = {"l1_hits": 0, "l2_hits": 0, "l3_hits": 0, "l4_hits": 0, "new_items": 0}

    def load_from_db(self, db_items: List[NewsItem]):
        """从数据库加载最近的条目到滑动窗口（用于启动时预热）"""
        with self._window_lock:
            for item in db_items:
                if not item.title_hash and item.title:
                    item.title_hash = compute_normalized_title_hash(item.title)
                if not item.content_simhash and item.title:
                    content = f"{item.title} {item.intro[:200]}" if item.intro else item.title
                    item.content_simhash = simhash_to_hex(compute_simhash(content))
                entry = CachedEntry(
                    news_id=item.id or 0,
                    title_hash=item.title_hash,
                    simhash=hex_to_simhash(item.content_simhash) if item.content_simhash else 0,
                    publish_ts=item.publish_ts,
                    source=item.source,
                    priority=get_source_priority(item.source),
                    keywords=set(item.keywords) if item.keywords else set(),
                    stocks=set(item.stocks) if item.stocks else set(),
                    url=item.url or "",
                )
                if item.url and item.url != "#":
                    self._url_index[item.url] = entry
                if item.title_hash:
                    self._title_hash_index[item.title_hash] = entry
                if entry.simhash != 0:
                    self._simhash_list.append((entry.simhash, entry))
                self._window.append(entry)
            logger.info(f"去重引擎预热完成：加载 {len(db_items)} 条历史新闻到滑动窗口")


# 全局单例
_dedup_engine: Optional[DedupEngine] = None


def get_dedup_engine() -> DedupEngine:
    global _dedup_engine
    if _dedup_engine is None:
        _dedup_engine = DedupEngine()
    return _dedup_engine


def deduplicate(news_list: List[NewsItem]) -> List[NewsItem]:
    """兼容旧接口：仅做同批次简单去重（按url+source+title）"""
    if not news_list:
        return []
    seen = set()
    result = []
    for n in news_list:
        key = (n.url, n.source, n.title)
        if key not in seen:
            seen.add(key)
            result.append(n)
    return result
