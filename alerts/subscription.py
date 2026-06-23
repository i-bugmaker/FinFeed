#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自选股与主题订阅管理

功能：
- 自选股增删改查
- 主题订阅（关键词组合）
- 新闻匹配判断
"""

import json
import sqlite3
from typing import Optional

from storage.database import get_db
from utils.time_utils import now_bj


# ============================================================
# 自选股管理
# ============================================================

def add_stock(stock_code: str, stock_name: str = "") -> bool:
    """添加自选股"""
    stock_code = stock_code.upper().strip()
    if not stock_code:
        return False
    with get_db() as conn:
        c = conn.cursor()
        now_str = now_bj().strftime("%Y-%m-%d %H:%M:%S")
        try:
            c.execute(
                "INSERT OR IGNORE INTO watchlist (stock_code, stock_name, added_at) VALUES (?, ?, ?)",
                (stock_code, stock_name or stock_code, now_str)
            )
            conn.commit()
            return c.rowcount > 0
        except Exception:
            return False


def remove_stock(stock_code: str) -> bool:
    """移除自选股"""
    stock_code = stock_code.upper().strip()
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM watchlist WHERE stock_code = ?", (stock_code,))
        conn.commit()
        return c.rowcount > 0


def get_watchlist() -> list[dict]:
    """获取自选股列表"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT stock_code, stock_name, added_at FROM watchlist ORDER BY added_at DESC")
        return [
            {"code": row[0], "name": row[1], "added_at": row[2]}
            for row in c.fetchall()
        ]


def is_stock_watched(stock_code: str) -> bool:
    """检查某股票是否在自选股中"""
    stock_code = stock_code.upper().strip()
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM watchlist WHERE stock_code = ? LIMIT 1", (stock_code,))
        return c.fetchone() is not None


# ============================================================
# 主题订阅管理
# ============================================================

def add_topic(name: str, keywords: list[str], description: str = "") -> int:
    """添加主题订阅

    Args:
        name: 主题名称
        keywords: 关键词列表
        description: 主题描述

    Returns:
        主题 ID，失败返回 0
    """
    if not name or not keywords:
        return 0
    with get_db() as conn:
        c = conn.cursor()
        now_str = now_bj().strftime("%Y-%m-%d %H:%M:%S")
        try:
            c.execute(
                "INSERT INTO topics (name, keywords, description, created_at, is_enabled) VALUES (?, ?, ?, ?, 1)",
                (name, json.dumps(keywords, ensure_ascii=False), description, now_str)
            )
            conn.commit()
            return c.lastrowid
        except Exception:
            return 0


def remove_topic(topic_id: int) -> bool:
    """删除主题订阅"""
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
        conn.commit()
        return c.rowcount > 0


def get_topics(enabled_only: bool = True) -> list[dict]:
    """获取主题列表"""
    with get_db() as conn:
        c = conn.cursor()
        if enabled_only:
            c.execute(
                "SELECT id, name, keywords, description, created_at, is_enabled FROM topics WHERE is_enabled = 1 ORDER BY created_at DESC"
            )
        else:
            c.execute(
                "SELECT id, name, keywords, description, created_at, is_enabled FROM topics ORDER BY created_at DESC"
            )
        return [
            {
                "id": row[0],
                "name": row[1],
                "keywords": json.loads(row[2]) if row[2] else [],
                "description": row[3] or "",
                "created_at": row[4],
                "is_enabled": bool(row[5]),
            }
            for row in c.fetchall()
        ]


# ============================================================
# 新闻匹配
# ============================================================

def match_watchlist_news(news_stocks: list[str]) -> list[str]:
    """判断新闻涉及的股票是否在自选股中

    Returns:
        匹配的股票代码列表
    """
    if not news_stocks:
        return []
    watchlist = get_watchlist()
    watched_codes = {s["code"] for s in watchlist}
    return [code for code in news_stocks if code.upper() in watched_codes]


def match_topics_news(title: str, intro: str = "") -> list[dict]:
    """判断新闻匹配哪些主题

    匹配规则：新闻包含主题的任意一个关键词即命中（后续可扩展为 AND 模式）

    Returns:
        匹配的主题列表
    """
    text = f"{title} {intro}"
    topics = get_topics(enabled_only=True)
    matched = []
    for topic in topics:
        for kw in topic["keywords"]:
            if kw and kw in text:
                matched.append(topic)
                break
    return matched
