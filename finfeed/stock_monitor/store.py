#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""股票监控模块 — 存储层。

三张表（复用主库 ``finfeed.storage.database.get_db``，与主系统同库同连接池）：

- ``stock_watchlist``   监控股票列表（code 主键 + 名称/市场/板块/备注）
- ``stock_messages``    系统外消息缓存（东方财富个股资讯 + 公告，
                        以 (code, dedup_key) 唯一键幂等入库）
- ``stock_analyses``    AI 分析结果（与股票 code 关联，status 驱动任务轮询）

系统内消息不镜像缓存，聚合时实时按代码/名称 LIKE 匹配 ``news`` 表，
保证与快讯/财经/舆情三个模块的数据口径始终一致。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from finfeed.storage.database import get_db
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("stock_monitor")

_DDL = """
CREATE TABLE IF NOT EXISTS stock_watchlist (
    code       TEXT PRIMARY KEY,
    name       TEXT DEFAULT '',
    market     TEXT DEFAULT '',
    board      TEXT DEFAULT '',
    note       TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS stock_messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT NOT NULL,
    source_type   TEXT DEFAULT 'external',
    channel       TEXT DEFAULT '',
    title         TEXT DEFAULT '',
    url           TEXT DEFAULT '',
    summary       TEXT DEFAULT '',
    source        TEXT DEFAULT '',
    publish_time  TEXT DEFAULT '',
    publish_ts    INTEGER DEFAULT 0,
    dedup_key     TEXT DEFAULT '',
    first_seen_ts INTEGER DEFAULT 0,
    UNIQUE(code, dedup_key)
);

CREATE INDEX IF NOT EXISTS idx_stock_messages_code_ts
    ON stock_messages (code, publish_ts DESC);
CREATE INDEX IF NOT EXISTS idx_stock_messages_id
    ON stock_messages (id);

CREATE TABLE IF NOT EXISTS stock_analyses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL,
    status      TEXT DEFAULT 'running',
    model       TEXT DEFAULT '',
    content     TEXT DEFAULT '',
    sentiment   TEXT DEFAULT '',
    impact      TEXT DEFAULT '',
    msg_count   INTEGER DEFAULT 0,
    error       TEXT DEFAULT '',
    created_at  TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_stock_analyses_code
    ON stock_analyses (code, id DESC);
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
    logger.info("stock_monitor 数据表已就绪")


# 监控列表 CRUD
def upsert_stock(code: str, name: str, market: str, board: str, note: str = "") -> bool:
    """新增/更新监控股票；已存在时仅补充名称等元数据，不覆盖备注。"""
    ensure_tables()
    now = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as c:
        c.execute(
            """
            INSERT INTO stock_watchlist (code, name, market, board, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name = CASE WHEN excluded.name != '' THEN excluded.name ELSE stock_watchlist.name END,
                market = CASE WHEN excluded.market != '' THEN excluded.market ELSE stock_watchlist.market END,
                board = CASE WHEN excluded.board != '' THEN excluded.board ELSE stock_watchlist.board END,
                updated_at = excluded.updated_at
            """,
            (code, name, market, board, note, now, now),
        )
    return True


def list_stocks() -> List[Dict[str, Any]]:
    ensure_tables()
    with get_db() as c:
        c.execute("SELECT * FROM stock_watchlist ORDER BY created_at ASC, code ASC")
        return [dict(r) for r in c.fetchall()]


def get_stock(code: str) -> Optional[Dict[str, Any]]:
    ensure_tables()
    with get_db() as c:
        c.execute("SELECT * FROM stock_watchlist WHERE code = ?", (code,))
        row = c.fetchone()
        return dict(row) if row else None


def update_stock_note(code: str, note: str) -> bool:
    ensure_tables()
    now = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as c:
        cur = c.execute(
            "UPDATE stock_watchlist SET note = ?, updated_at = ? WHERE code = ?",
            (note, now, code),
        )
        return cur.rowcount > 0


def delete_stock(code: str) -> bool:
    """删除监控股票（同时清理其外部消息缓存；AI 分析结果保留作历史）。"""
    ensure_tables()
    with get_db() as c:
        cur = c.execute("DELETE FROM stock_watchlist WHERE code = ?", (code,))
        c.execute("DELETE FROM stock_messages WHERE code = ?", (code,))
        return cur.rowcount > 0


# 系统外消息缓存
def insert_external_messages(items: List[Dict[str, Any]]) -> int:
    """幂等写入外部消息；返回实际新增条数。"""
    if not items:
        return 0
    ensure_tables()
    seen_ts = now_bj().timestamp().__int__()
    inserted = 0
    with get_db() as c:
        for it in items:
            try:
                cur = c.execute(
                    """
                    INSERT OR IGNORE INTO stock_messages
                        (code, source_type, channel, title, url, summary, source,
                         publish_time, publish_ts, dedup_key, first_seen_ts)
                    VALUES (?, 'external', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        it["code"],
                        it.get("channel", "news"),
                        it.get("title", ""),
                        it.get("url", ""),
                        it.get("summary", ""),
                        it.get("source", ""),
                        it.get("publish_time", ""),
                        int(it.get("publish_ts", 0)),
                        it.get("dedup_key", ""),
                        seen_ts,
                    ),
                )
                inserted += cur.rowcount
            except Exception as e:  # noqa: BLE001
                logger.warning("插入外部消息失败 code=%s: %s", it.get("code"), e)
    return inserted


def get_external_messages(
    codes: List[str],
    since_ts: int = 0,
    after_id: int = 0,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """读取外部消息缓存（按 code 过滤、时间/自增水位过滤、倒序）。"""
    ensure_tables()
    if not codes:
        return []
    placeholders = ",".join("?" for _ in codes)
    sql = f"""
        SELECT * FROM stock_messages
        WHERE code IN ({placeholders}) AND publish_ts >= ? AND id > ?
        ORDER BY publish_ts DESC, id DESC LIMIT ?
    """
    with get_db() as c:
        c.execute(sql, (*codes, since_ts, after_id, limit))
        return [dict(r) for r in c.fetchall()]


def get_external_max_id(codes: List[str]) -> int:
    ensure_tables()
    if not codes:
        return 0
    placeholders = ",".join("?" for _ in codes)
    with get_db() as c:
        c.execute(
            f"SELECT COALESCE(MAX(id), 0) AS m FROM stock_messages WHERE code IN ({placeholders})",
            codes,
        )
        return int(c.fetchone()["m"])


# 系统内消息匹配（news 表实时查询）
def get_internal_messages(
    codes: List[str],
    names: Dict[str, str],
    since_ts: int = 0,
    after_id: int = 0,
    limit: int = 300,
) -> List[Dict[str, Any]]:
    """从 news 表检索关联消息，基于「标题/简介真的出现该股票名或代码」。

    说明：news.stocks 字段由上游打标，已证实存在系统性噪声（热股榜整榜误标、
    实体识别错误等），因此不再用它作为关联依据。只有消息标题或简介中出现
    监控股票的名称（≥2 字）或代码，才判定为与该股票相关。

    返回条目附带 ``codes``（命中的监控代码列表），供前端按股票分组。
    """
    ensure_tables()
    if not codes:
        return []
    conds = []
    params: List[Any] = []
    for code in codes:
        conds.append("title LIKE ?")
        params.append(f"%{code}%")
        name = (names.get(code) or "").strip()
        if len(name) >= 2:
            conds.append("title LIKE ?")
            params.append(f"%{name}%")
    since_cond = ""
    if since_ts > 0:
        since_cond = " AND publish_ts >= ?"
        params.append(since_ts)
    if after_id > 0:
        since_cond += " AND id > ?"
        params.append(after_id)
    sql = f"""
        SELECT id, title, url, source, category, publish_time, publish_ts,
               intro, sentiment, importance, stocks
        FROM news
        WHERE ({' OR '.join(conds)}){since_cond}
        ORDER BY publish_ts DESC, id DESC LIMIT ?
    """
    params.append(limit)
    out: List[Dict[str, Any]] = []
    with get_db() as c:
        c.execute(sql, params)
        for r in c.fetchall():
            item = dict(r)
            title = item.get("title") or ""
            intro = item.get("intro") or ""
            hay = f"{title} {intro}".upper()
            hit: List[str] = []
            for code in codes:
                name = (names.get(code) or "").strip()
                if code in hay or (len(name) >= 2 and name.upper() in hay):
                    hit.append(code)
            item["codes"] = hit
            item["source_type"] = "internal"
            out.append(item)
    return out


# AI 分析结果
def create_analysis(code: str) -> int:
    ensure_tables()
    now = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as c:
        cur = c.execute(
            "INSERT INTO stock_analyses (code, status, created_at) VALUES (?, 'running', ?)",
            (code, now),
        )
        return int(cur.lastrowid)


def finish_analysis(analysis_id: int, *, content: str, sentiment: str,
                    impact: str, model: str, msg_count: int) -> None:
    now = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as c:
        c.execute(
            """
            UPDATE stock_analyses
            SET status='done', content=?, sentiment=?, impact=?, model=?,
                msg_count=?, finished_at=?
            WHERE id=?
            """,
            (content, sentiment, impact, model, msg_count, now, analysis_id),
        )


def fail_analysis(analysis_id: int, error: str) -> None:
    now = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as c:
        c.execute(
            "UPDATE stock_analyses SET status='failed', error=?, finished_at=? WHERE id=?",
            (error[:500], now, analysis_id),
        )


def get_analysis(analysis_id: int) -> Optional[Dict[str, Any]]:
    ensure_tables()
    with get_db() as c:
        c.execute("SELECT * FROM stock_analyses WHERE id = ?", (analysis_id,))
        row = c.fetchone()
        return dict(row) if row else None


def get_latest_analysis(code: str) -> Optional[Dict[str, Any]]:
    ensure_tables()
    with get_db() as c:
        c.execute(
            "SELECT * FROM stock_analyses WHERE code = ? ORDER BY id DESC LIMIT 1", (code,)
        )
        row = c.fetchone()
        return dict(row) if row else None


def list_analyses(code: str, limit: int = 10) -> List[Dict[str, Any]]:
    ensure_tables()
    with get_db() as c:
        c.execute(
            "SELECT * FROM stock_analyses WHERE code = ? ORDER BY id DESC LIMIT ?",
            (code, limit),
        )
        return [dict(r) for r in c.fetchall()]
