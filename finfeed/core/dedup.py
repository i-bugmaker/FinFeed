#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻去重模块（已重构：去重逻辑下沉到数据库层唯一索引，此文件保留空接口兼容）"""

import logging
from typing import List

from finfeed.storage.models import NewsItem

logger = logging.getLogger("news_monitor")


class DeduplicationEngine:
    """去重引擎（空实现：数据库层通过(url, source)唯一索引自动去重）"""

    def __init__(self) -> None:
        pass

    def is_duplicate(self, news: NewsItem) -> bool:
        """检查新闻是否重复（始终返回False，由数据库INSERT OR IGNORE处理）"""
        return False

    def add_seen(self, news: NewsItem) -> None:
        """标记新闻为已见（空操作）"""
        pass

    def deduplicate(self, news_list: List[NewsItem]) -> List[NewsItem]:
        """内存级去重：仅过滤同批内完全相同的URL+source+title"""
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

    def clear_memory(self) -> None:
        """清空内存缓存（空操作）"""
        pass


_global_dedup = DeduplicationEngine()


def get_dedup_engine() -> DeduplicationEngine:
    return _global_dedup
