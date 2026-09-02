#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自选股与主题订阅管理

- 自选股：复用 ``stock_monitor.stock_watchlist``（与股票监控模块同一份数据源，
  用户在「股票监控」页导入的股票自动参与告警匹配）
- 主题订阅：``alerts.store.topics`` 表（关键词组合，命中即推送）
- 新闻匹配判断（供 dispatcher 调用）
"""

import logging

from finfeed.alerts import store

logger = logging.getLogger("news_monitor")

# 自选股管理（委托 stock_monitor.store）

def add_stock(stock_code: str, stock_name: str = "") -> bool:
    """添加自选股"""
    from finfeed.stock_monitor import store as sm_store

    stock_code = stock_code.upper().strip()
    if not stock_code:
        return False
    return sm_store.upsert_stock(stock_code, stock_name or stock_code, "", "")


def remove_stock(stock_code: str) -> bool:
    """移除自选股"""
    from finfeed.stock_monitor import store as sm_store

    return sm_store.delete_stock(stock_code.upper().strip())


def get_watchlist() -> list[dict]:
    """获取自选股列表"""
    from finfeed.stock_monitor import store as sm_store

    return [
        {"code": s["code"], "name": s.get("name") or s["code"], "added_at": s.get("created_at") or ""}
        for s in sm_store.list_stocks()
    ]


def is_stock_watched(stock_code: str) -> bool:
    """检查某股票是否在自选股中"""
    stock_code = stock_code.upper().strip()
    return any(s["code"] == stock_code for s in get_watchlist())


# 主题订阅管理

def add_topic(name: str, keywords: list[str], description: str = "") -> int:
    """添加主题订阅，返回主题 ID（失败返回 0）"""
    t = store.create_topic(name, keywords, description)
    return t["id"] if t else 0


def remove_topic(topic_id: int) -> bool:
    """删除主题订阅"""
    return store.delete_topic(topic_id)


def get_topics(enabled_only: bool = True) -> list[dict]:
    """获取主题列表"""
    return store.list_topics(enabled_only=enabled_only)


def set_topic_enabled(topic_id: int, enabled: bool) -> bool:
    """启用/停用主题订阅"""
    return store.update_topic(topic_id, {"is_enabled": enabled}) is not None


# 新闻匹配

def match_watchlist_news(news_stocks: list[str]) -> list[str]:
    """判断新闻涉及的股票是否在自选股中

    Returns:
        匹配的股票代码列表
    """
    if not news_stocks:
        return []
    watched_codes = {s["code"] for s in get_watchlist()}
    return [code for code in news_stocks if code.upper() in watched_codes]


def match_topics_news(title: str, intro: str = "") -> list[dict]:
    """判断新闻匹配哪些主题

    匹配规则：新闻包含主题的任意一个关键词即命中（后续可扩展为 AND 模式）

    Returns:
        匹配的主题列表
    """
    text = f"{title} {intro}"
    matched = []
    for topic in get_topics(enabled_only=True):
        for kw in topic["keywords"]:
            if kw and kw in text:
                matched.append(topic)
                break
    return matched
