#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据模型定义"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NewsItem:
    """新闻条目数据类"""
    title: str
    url: str = "#"
    source: str = ""
    publish_time: str = ""
    publish_ts: int = 0
    intro: str = ""
    title_full_hash: str = ""
    url_hash: str = ""
    simhash: int = 0
    id: Optional[int] = None
    created_at: str = ""
    category: str = ""
    sentiment: str = "neutral"
    importance: float = 0.0
    keywords: list = field(default_factory=list)
    stocks: list = field(default_factory=list)
    is_read: bool = False
    is_favorite: bool = False
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "publish_time": self.publish_time,
            "publish_ts": self.publish_ts,
            "intro": self.intro,
            "category": self.category,
            "sentiment": self.sentiment,
            "importance": self.importance,
            "keywords": self.keywords,
            "stocks": self.stocks,
            "is_read": self.is_read,
            "is_favorite": self.is_favorite,
            "tags": self.tags,
        }


@dataclass
class SourceHealth:
    """数据源健康状态"""
    source_name: str
    total_requests: int = 0
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    avg_latency: float = 0.0
    last_success_ts: int = 0
    last_failure_ts: int = 0
    last_error: str = ""
    is_circuit_open: bool = False
    circuit_open_ts: int = 0

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.success_count / self.total_requests
