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
    content: str = ""
    id: Optional[int] = None
    created_at: str = ""
    category: str = ""
    sentiment: str = "neutral"
    importance: float = 0.0
    keywords: list[str] = field(default_factory=list)
    stocks: list[str] = field(default_factory=list)
    is_read: bool = False
    is_favorite: bool = False
    title_hash: str = ""
    content_simhash: str = ""
    duplicate_count: int = 0
    duplicate_sources: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "publish_time": self.publish_time,
            "publish_ts": self.publish_ts,
            "intro": self.intro,
            "content": self.content,
            "category": self.category,
            "sentiment": self.sentiment,
            "importance": self.importance,
            "keywords": self.keywords,
            "stocks": self.stocks,
            "is_read": self.is_read,
            "is_favorite": self.is_favorite,
            "duplicate_count": self.duplicate_count,
            "duplicate_sources": self.duplicate_sources,
            "meta": self.meta,
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
