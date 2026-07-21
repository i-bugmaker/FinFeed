#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据统计与可视化

提供各类统计数据，用于可视化大屏和数据分析。
"""

import time
from collections import Counter, defaultdict
from typing import Optional

from storage.database import get_db


def get_source_stats(hours: int = 24) -> dict[str, int]:
    """获取各来源的新闻数量统计

    Args:
        hours: 统计最近多少小时的数据

    Returns:
        {来源名称: 新闻数量}
    """
    cutoff_ts = int(time.time()) - hours * 3600
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT source, COUNT(*) as cnt FROM news WHERE publish_ts >= ? GROUP BY source ORDER BY cnt DESC",
            (cutoff_ts,)
        )
        return {row[0]: row[1] for row in c.fetchall()}


def get_category_stats(hours: int = 24) -> dict[str, int]:
    """获取分类统计"""
    cutoff_ts = int(time.time()) - hours * 3600
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT category, COUNT(*) as cnt FROM news WHERE publish_ts >= ? AND category != '' GROUP BY category ORDER BY cnt DESC",
            (cutoff_ts,)
        )
        return {row[0]: row[1] for row in c.fetchall()}


def get_sentiment_stats(hours: int = 24) -> dict[str, int]:
    """获取情感分布统计"""
    cutoff_ts = int(time.time()) - hours * 3600
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT sentiment, COUNT(*) as cnt FROM news WHERE publish_ts >= ? AND sentiment != 'neutral' GROUP BY sentiment",
            (cutoff_ts,)
        )
        result = {"positive": 0, "neutral": 0, "negative": 0}
        for row in c.fetchall():
            result[row[0]] = row[1]
        # 计算中性新闻数
        total = get_total_news(hours)
        result["neutral"] = total - result["positive"] - result["negative"]
        return result


def get_importance_distribution(hours: int = 24) -> dict[str, int]:
    """获取重要性分布"""
    cutoff_ts = int(time.time()) - hours * 3600
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT importance FROM news WHERE publish_ts >= ? AND importance > 0",
            (cutoff_ts,)
        )
        levels = {"极重要": 0, "重要": 0, "一般": 0, "较低": 0, "低": 0}
        for row in c.fetchall():
            score = row[0]
            if score >= 8.0:
                levels["极重要"] += 1
            elif score >= 6.5:
                levels["重要"] += 1
            elif score >= 5.0:
                levels["一般"] += 1
            elif score >= 3.0:
                levels["较低"] += 1
            else:
                levels["低"] += 1
        return levels


def get_time_trend(hours: int = 24, bucket_hours: int = 1) -> list[dict]:
    """获取时间趋势数据

    Args:
        hours: 统计最近多少小时
        bucket_hours: 每个时间桶的大小（小时）

    Returns:
        [{time: 时间标签, count: 数量}, ...]
    """
    cutoff_ts = int(time.time()) - hours * 3600
    bucket_secs = bucket_hours * 3600

    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT publish_ts FROM news WHERE publish_ts >= ? ORDER BY publish_ts",
            (cutoff_ts,)
        )
        buckets = defaultdict(int)
        for row in c.fetchall():
            ts = row[0]
            bucket_ts = (ts // bucket_secs) * bucket_secs
            buckets[bucket_ts] += 1

    result = []
    now_ts = int(time.time())
    start_ts = (cutoff_ts // bucket_secs) * bucket_secs
    for ts in range(start_ts, now_ts + bucket_secs, bucket_secs):
        time_label = time.strftime("%H:%M", time.localtime(ts))
        result.append({
            "time": time_label,
            "count": buckets.get(ts, 0),
        })

    return result


def get_top_keywords(hours: int = 24, limit: int = 20) -> list[tuple[str, int]]:
    """获取热门关键词"""
    cutoff_ts = int(time.time()) - hours * 3600
    with get_db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT keywords FROM news WHERE publish_ts >= ? AND keywords != '[]'",
            (cutoff_ts,)
        )
        import json
        counter = Counter()
        for row in c.fetchall():
            try:
                kws = json.loads(row[0])
                for kw in kws[:3]:
                    counter[kw] += 1
            except Exception:
                pass
        return counter.most_common(limit)


def get_total_news(hours: Optional[int] = None) -> int:
    """获取总新闻数"""
    with get_db() as conn:
        c = conn.cursor()
        if hours:
            cutoff_ts = int(time.time()) - hours * 3600
            c.execute("SELECT COUNT(*) FROM news WHERE publish_ts >= ?", (cutoff_ts,))
        else:
            c.execute("SELECT COUNT(*) FROM news")
        return c.fetchone()[0]


def get_dashboard_stats(range_type: str = "24h") -> dict:
    """获取仪表盘汇总数据

    Args:
        range_type: 时间范围类型，支持 "24h", "7d", "30d"
    """
    hours_map = {
        "24h": 24,
        "7d": 168,
        "30d": 720,
    }
    hours = hours_map.get(range_type, 24)

    total = get_total_news()
    total_range = get_total_news(hours)
    source_stats = get_source_stats(hours)
    category_stats = get_category_stats(hours)
    sentiment_stats = get_sentiment_stats(hours)
    importance_dist = get_importance_distribution(hours)
    bucket_hours = 1 if hours <= 24 else 6 if hours <= 168 else 24
    time_trend = get_time_trend(hours, bucket_hours)
    top_keywords = get_top_keywords(hours, 20)

    return {
        "total_news": total,
        "total_24h": total_range,
        "source_count": len(source_stats),
        "source_stats": source_stats,
        "category_stats": category_stats,
        "sentiment_stats": sentiment_stats,
        "importance_distribution": importance_dist,
        "time_trend": time_trend,
        "keyword_stats": [{"word": kw, "count": cnt} for kw, cnt in top_keywords],
        "update_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    }
