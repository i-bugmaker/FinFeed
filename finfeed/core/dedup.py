#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻去重模块

跨源/跨批次的去重由数据库层 (url, source) 唯一索引 + INSERT OR IGNORE 处理。
本模块仅负责同批次内的内存级去重，避免相同 (url, source, title) 的条目重复入库。
"""

from typing import List

from finfeed.storage.models import NewsItem


def deduplicate(news_list: List[NewsItem]) -> List[NewsItem]:
    """同批次内按 (url, source, title) 去重，保留首次出现"""
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
