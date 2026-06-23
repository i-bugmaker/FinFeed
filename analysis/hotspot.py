#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""热点追踪与事件聚类

功能：
- 热门关键词统计（按时间窗口）
- 基于 SimHash + 关键词的事件聚类
- 热点热度计算与排名
"""

import time
from collections import Counter, defaultdict
from typing import Optional

from storage.models import NewsItem
from utils.hash_utils import compute_simhash, hamming_distance


class HotspotTracker:
    """热点追踪器"""

    def __init__(self, window_hours: int = 24, max_clusters: int = 50):
        self.window_hours = window_hours
        self.max_clusters = max_clusters
        self._news_window: list[NewsItem] = []
        self._clusters: list[dict] = []
        self._keyword_counter: Counter = Counter()

    def add_news(self, news_list: list[NewsItem]):
        """添加新闻到时间窗口"""
        now_ts = int(time.time())
        cutoff_ts = now_ts - self.window_hours * 3600

        # 添加新新闻
        self._news_window.extend(news_list)

        # 移除窗口外的旧新闻
        self._news_window = [
            n for n in self._news_window
            if n.publish_ts and n.publish_ts >= cutoff_ts
        ]

        # 限制窗口大小
        if len(self._news_window) > 5000:
            self._news_window = self._news_window[-5000:]

        # 更新关键词统计
        self._update_keywords()

    def _update_keywords(self):
        """更新热门关键词统计"""
        self._keyword_counter = Counter()
        for n in self._news_window:
            if n.keywords:
                for kw in n.keywords[:3]:  # 只取前3个关键词
                    self._keyword_counter[kw] += 1

    def get_hot_keywords(self, top_n: int = 20) -> list[tuple[str, int]]:
        """获取热门关键词

        Returns:
            (关键词, 出现次数) 列表，按热度降序
        """
        return self._keyword_counter.most_common(top_n)

    def get_hot_topics(self, top_n: int = 10) -> list[dict]:
        """获取热点话题（事件聚类）

        基于 SimHash + 关键词共现的简化聚类算法。

        Returns:
            热点话题列表，每项包含：
            - title: 话题代表标题
            - keywords: 话题关键词
            - news_count: 相关新闻数量
            - sources: 涉及的来源
            - first_ts: 最早时间戳
            - last_ts: 最晚时间戳
            - heat_score: 热度评分
        """
        if not self._news_window:
            return []

        # 按时间排序（最新的在前）
        sorted_news = sorted(
            self._news_window, key=lambda x: x.publish_ts, reverse=True
        )

        clusters: list[dict] = []

        for news in sorted_news[:1000]:  # 只聚类最近的1000条
            if not news.simhash:
                continue

            matched = False
            best_cluster = None
            best_sim = 0

            # 找最匹配的簇
            for cluster in clusters:
                # 计算与簇中心的相似度
                dist = hamming_distance(news.simhash, cluster["center_simhash"])
                sim = 1.0 - dist / 64.0

                # 关键词重叠度
                news_kws = set(news.keywords[:3]) if news.keywords else set()
                cluster_kws = set(cluster["keywords"][:3])
                kw_overlap = len(news_kws & cluster_kws) / max(len(news_kws | cluster_kws), 1)

                # 综合相似度
                total_sim = sim * 0.6 + kw_overlap * 0.4

                if total_sim > 0.55 and total_sim > best_sim:
                    best_sim = total_sim
                    best_cluster = cluster

            if best_cluster:
                # 加入簇
                best_cluster["news"].append(news)
                best_cluster["news_count"] += 1
                if news.source not in best_cluster["sources"]:
                    best_cluster["sources"].append(news.source)
                if news.publish_ts < best_cluster["first_ts"]:
                    best_cluster["first_ts"] = news.publish_ts
                if news.publish_ts > best_cluster["last_ts"]:
                    best_cluster["last_ts"] = news.publish_ts

                # 更新关键词
                for kw in news.keywords[:3]:
                    if kw not in best_cluster["keyword_counts"]:
                        best_cluster["keyword_counts"][kw] = 0
                    best_cluster["keyword_counts"][kw] += 1

                # 更新簇中心（取最新的作为代表）
                if news.publish_ts > best_cluster["latest_ts"]:
                    best_cluster["center_simhash"] = news.simhash
                    best_cluster["title"] = news.title
                    best_cluster["latest_ts"] = news.publish_ts

                matched = True

            if not matched and len(clusters) < self.max_clusters:
                # 创建新簇
                clusters.append({
                    "title": news.title,
                    "center_simhash": news.simhash,
                    "news": [news],
                    "news_count": 1,
                    "sources": [news.source],
                    "first_ts": news.publish_ts,
                    "last_ts": news.publish_ts,
                    "latest_ts": news.publish_ts,
                    "keyword_counts": {kw: 1 for kw in news.keywords[:3]},
                })

        # 计算热度并排序
        for cluster in clusters:
            # 热度 = 新闻数 * 来源数 * 时间衰减因子
            news_count = cluster["news_count"]
            source_count = len(cluster["sources"])

            # 时间衰减：越新的话题热度越高
            now_ts = int(time.time())
            age_hours = (now_ts - cluster["latest_ts"]) / 3600
            decay = max(0.1, 1.0 - age_hours / self.window_hours)

            cluster["heat_score"] = round(
                news_count * (1 + source_count * 0.3) * decay * 10, 1
            )

            # 提取 top 关键词
            sorted_kws = sorted(
                cluster["keyword_counts"].items(),
                key=lambda x: x[1], reverse=True
            )
            cluster["keywords"] = [kw for kw, _ in sorted_kws[:5]]

        # 按热度排序
        clusters.sort(key=lambda x: x["heat_score"], reverse=True)

        # 清理内部字段
        result = []
        for c in clusters[:top_n]:
            result.append({
                "title": c["title"],
                "keywords": c["keywords"],
                "news_count": c["news_count"],
                "sources": c["sources"],
                "first_ts": c["first_ts"],
                "last_ts": c["last_ts"],
                "heat_score": c["heat_score"],
            })

        return result


_global_tracker: Optional[HotspotTracker] = None


def get_hotspot_tracker() -> HotspotTracker:
    """获取全局热点追踪器单例"""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = HotspotTracker()
    return _global_tracker
