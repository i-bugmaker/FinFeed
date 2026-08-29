#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""告警推送模块 — 存储层。

四张表（复用主库 ``finfeed.storage.database.get_db``，与主系统同库同连接池）：

- ``topics``          主题订阅（关键词组合，命中即推送）
- ``webhooks``        推送渠道配置（钉钉/企业微信/飞书/Telegram/Server酱，
                      持久化保存，重启不丢失）
- ``alert_settings``  告警全局设置（key-value：总开关/基准阈值/免打扰等）
- ``alert_push_log``  推送日志（(news_id, webhook_id) 唯一键做推送幂等去重）

自选股订阅不在此建表：直接复用 ``stock_monitor.stock_watchlist``，
与股票监控模块保持同一份自选股数据源。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from finfeed.storage.database import get_db
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("news_monitor")

_DDL = """
CREATE TABLE IF NOT EXISTS topics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    keywords    TEXT DEFAULT '[]',
    description TEXT DEFAULT '',
    created_at  TEXT,
    is_enabled  INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS webhooks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT DEFAULT '',
    type           TEXT NOT NULL,
    url            TEXT NOT NULL,
    extra          TEXT DEFAULT '',
    enabled        INTEGER DEFAULT 1,
    min_importance REAL DEFAULT 0.0,
    quiet_start    TEXT DEFAULT '',
    quiet_end      TEXT DEFAULT '',
    created_at     TEXT,
    updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS alert_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_push_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id    INTEGER NOT NULL,
    webhook_id INTEGER NOT NULL,
    pushed_at  TEXT,
    UNIQUE(news_id, webhook_id)
);

CREATE INDEX IF NOT EXISTS idx_alert_push_log_time
    ON alert_push_log (pushed_at DESC);
"""

_tables_ready = False


def ensure_tables() -> None:
    """幂等建表（模块首次使用 / 应用启动时调用）。"""
    global _tables_ready
    if _tables_ready:
        return
    with get_db() as c:
        c.executescript(_DDL)
    _tables_ready = True
    logger.info("alerts 数据表已就绪")


# ============================================================
# Webhook 渠道 CRUD
# ============================================================

WEBHOOK_TYPES = ("dingtalk", "wecom", "feishu", "telegram", "serverchan")

_WEBHOOK_COLS = (
    "id, name, type, url, extra, enabled, min_importance, "
    "quiet_start, quiet_end, created_at, updated_at"
)


def _row_to_webhook(row) -> dict:
    return {
        "id": row[0],
        "name": row[1] or "",
        "type": row[2],
        "url": row[3],
        "extra": row[4] or "",
        "enabled": bool(row[5]),
        "min_importance": row[6] if row[6] is not None else 0.0,
        "quiet_start": row[7] or "",
        "quiet_end": row[8] or "",
        "created_at": row[9],
        "updated_at": row[10],
    }


def list_webhooks(enabled_only: bool = False) -> List[dict]:
    ensure_tables()
    with get_db() as c:
        sql = f"SELECT {_WEBHOOK_COLS} FROM webhooks"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY id"
        return [_row_to_webhook(r) for r in c.execute(sql).fetchall()]


def get_webhook(webhook_id: int) -> Optional[dict]:
    ensure_tables()
    with get_db() as c:
        row = c.execute(
            f"SELECT {_WEBHOOK_COLS} FROM webhooks WHERE id = ?", (webhook_id,)
        ).fetchone()
        return _row_to_webhook(row) if row else None


def create_webhook(data: dict) -> Optional[dict]:
    ensure_tables()
    if data.get("type") not in WEBHOOK_TYPES:
        return None
    if not (data.get("url") or "").strip():
        return None
    now = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_db() as c:
            cur = c.execute(
                """INSERT INTO webhooks
                   (name, type, url, extra, enabled, min_importance,
                    quiet_start, quiet_end, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    (data.get("name") or "").strip(),
                    data["type"],
                    data["url"].strip(),
                    (data.get("extra") or "").strip(),
                    1 if data.get("enabled", True) else 0,
                    float(data.get("min_importance") or 0.0),
                    data.get("quiet_start") or "",
                    data.get("quiet_end") or "",
                    now, now,
                ),
            )
            return get_webhook(cur.lastrowid)
    except Exception as e:
        logger.warning(f"创建 webhook 失败: {e}")
        return None


def update_webhook(webhook_id: int, data: dict) -> Optional[dict]:
    ensure_tables()
    existing = get_webhook(webhook_id)
    if not existing:
        return None
    if "type" in data and data["type"] not in WEBHOOK_TYPES:
        return None
    merged = {**existing, **data}
    now = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_db() as c:
            c.execute(
                """UPDATE webhooks SET name = ?, type = ?, url = ?, extra = ?,
                   enabled = ?, min_importance = ?, quiet_start = ?, quiet_end = ?,
                   updated_at = ? WHERE id = ?""",
                (
                    (merged.get("name") or "").strip(),
                    merged["type"],
                    merged["url"],
                    (merged.get("extra") or "").strip(),
                    1 if merged.get("enabled", True) else 0,
                    float(merged.get("min_importance") or 0.0),
                    merged.get("quiet_start") or "",
                    merged.get("quiet_end") or "",
                    now, webhook_id,
                ),
            )
        return get_webhook(webhook_id)
    except Exception as e:
        logger.warning(f"更新 webhook 失败: {e}")
        return None


def delete_webhook(webhook_id: int) -> bool:
    ensure_tables()
    with get_db() as c:
        c.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
        deleted = c.rowcount
        c.execute("DELETE FROM alert_push_log WHERE webhook_id = ?", (webhook_id,))
        return deleted > 0


# ============================================================
# 全局设置（key-value，带默认值）
# ============================================================

SETTING_DEFAULTS: Dict[str, str] = {
    "enabled": "1",                     # 告警推送总开关
    "base_importance": "5.0",           # 主题命中新闻的基准重要性阈值（受市场状态调节）
    "watchlist_min_importance": "0.0",  # 自选股命中新闻的最低重要性（0 = 全推）
    "use_regime": "1",                  # 是否按市场状态动态调节主题阈值
}


def get_settings() -> dict:
    ensure_tables()
    stored: Dict[str, str] = {}
    with get_db() as c:
        for k, v in c.execute("SELECT key, value FROM alert_settings").fetchall():
            stored[k] = v
    merged = {**SETTING_DEFAULTS, **stored}
    return {
        "enabled": merged["enabled"] == "1",
        "base_importance": float(merged["base_importance"] or 5.0),
        "watchlist_min_importance": float(merged["watchlist_min_importance"] or 0.0),
        "use_regime": merged["use_regime"] == "1",
    }


def update_settings(data: dict) -> dict:
    ensure_tables()
    allowed = {
        "enabled": lambda v: "1" if v else "0",
        "base_importance": lambda v: str(round(float(v), 2)),
        "watchlist_min_importance": lambda v: str(round(float(v), 2)),
        "use_regime": lambda v: "1" if v else "0",
    }
    with get_db() as c:
        for k, v in (data or {}).items():
            fn = allowed.get(k)
            if fn is None:
                continue
            c.execute(
                "INSERT OR REPLACE INTO alert_settings (key, value) VALUES (?, ?)",
                (k, fn(v)),
            )
    return get_settings()


# ============================================================
# 推送日志（幂等去重）
# ============================================================

def filter_fresh(news_ids: List[int], webhook_id: int) -> List[int]:
    """过滤出尚未推送过该渠道的新闻 id（唯一键约束保证不重复推送）。"""
    if not news_ids:
        return []
    ensure_tables()
    with get_db() as c:
        marks = ",".join("?" for _ in news_ids)
        rows = c.execute(
            f"SELECT news_id FROM alert_push_log WHERE webhook_id = ? AND news_id IN ({marks})",
            [webhook_id, *news_ids],
        ).fetchall()
    pushed = {r[0] for r in rows}
    return [nid for nid in news_ids if nid not in pushed]


def record_pushed(news_ids: List[int], webhook_id: int) -> int:
    if not news_ids:
        return 0
    ensure_tables()
    now = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as c:
        before = c.connection.total_changes if hasattr(c, "connection") else 0
        c.executemany(
            "INSERT OR IGNORE INTO alert_push_log (news_id, webhook_id, pushed_at) VALUES (?, ?, ?)",
            [(nid, webhook_id, now) for nid in news_ids],
        )
        after = c.connection.total_changes if hasattr(c, "connection") else 0
        return max(0, after - before)


def recent_push_log(limit: int = 50) -> List[dict]:
    ensure_tables()
    with get_db() as c:
        rows = c.execute(
            """SELECT l.id, l.news_id, l.webhook_id, l.pushed_at,
                      w.name, w.type, n.title, n.url, n.source, n.publish_time
               FROM alert_push_log l
               LEFT JOIN webhooks w ON w.id = l.webhook_id
               LEFT JOIN news n ON n.id = l.news_id
               ORDER BY l.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [
        {
            "id": r[0], "news_id": r[1], "webhook_id": r[2], "pushed_at": r[3],
            "webhook_name": r[4] or f"#{r[2]}", "webhook_type": r[5] or "",
            "title": r[6] or "", "url": r[7] or "", "source": r[8] or "",
            "publish_time": r[9] or "",
        }
        for r in rows
    ]


def prune_push_log(keep_days: int = 7) -> int:
    """清理过期推送日志（由调度器每日调用，防止表无限增长）。"""
    ensure_tables()
    with get_db() as c:
        c.execute(
            "DELETE FROM alert_push_log WHERE pushed_at < datetime('now', 'localtime', ?)",
            (f"-{keep_days} days",),
        )
        return c.rowcount


# ============================================================
# 主题订阅（关键词组合）
# ============================================================

def list_topics(enabled_only: bool = False) -> List[dict]:
    ensure_tables()
    with get_db() as c:
        sql = "SELECT id, name, keywords, description, created_at, is_enabled FROM topics"
        if enabled_only:
            sql += " WHERE is_enabled = 1"
        sql += " ORDER BY id DESC"
        return [
            {
                "id": r[0], "name": r[1],
                "keywords": json.loads(r[2]) if r[2] else [],
                "description": r[3] or "", "created_at": r[4],
                "is_enabled": bool(r[5]),
            }
            for r in c.execute(sql).fetchall()
        ]


def create_topic(name: str, keywords: List[str], description: str = "") -> Optional[dict]:
    ensure_tables()
    keywords = [k.strip() for k in (keywords or []) if k and k.strip()]
    if not name or not name.strip() or not keywords:
        return None
    now = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_db() as c:
            cur = c.execute(
                "INSERT INTO topics (name, keywords, description, created_at, is_enabled) VALUES (?, ?, ?, ?, 1)",
                (name.strip(), json.dumps(keywords, ensure_ascii=False), description, now),
            )
            tid = cur.lastrowid
        return next((t for t in list_topics() if t["id"] == tid), None)
    except Exception as e:
        logger.warning(f"创建主题订阅失败 {name}: {e}")
        return None


def update_topic(topic_id: int, data: dict) -> Optional[dict]:
    ensure_tables()
    with get_db() as c:
        row = c.execute("SELECT id FROM topics WHERE id = ?", (topic_id,)).fetchone()
        if not row:
            return None
        if "name" in data:
            c.execute("UPDATE topics SET name = ? WHERE id = ?", (data["name"], topic_id))
        if "description" in data:
            c.execute("UPDATE topics SET description = ? WHERE id = ?", (data["description"], topic_id))
        if "keywords" in data:
            kws = [k.strip() for k in (data["keywords"] or []) if k and k.strip()]
            c.execute(
                "UPDATE topics SET keywords = ? WHERE id = ?",
                (json.dumps(kws, ensure_ascii=False), topic_id),
            )
        if "is_enabled" in data:
            c.execute(
                "UPDATE topics SET is_enabled = ? WHERE id = ?",
                (1 if data["is_enabled"] else 0, topic_id),
            )
    return next((t for t in list_topics() if t["id"] == topic_id), None)


def delete_topic(topic_id: int) -> bool:
    ensure_tables()
    with get_db() as c:
        c.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
        return c.rowcount > 0


def calibration_latest() -> Optional[dict]:
    """读取最近一次情感闭环校准结果（metadata 表，由 crossref 校准任务写入）。"""
    try:
        with get_db() as c:
            row = c.execute(
                "SELECT value FROM metadata WHERE key = 'sentiment_calibration_latest'"
            ).fetchone()
    except Exception as e:
        logger.debug(f"读取校准结果失败: {e}")
        return None
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return None
