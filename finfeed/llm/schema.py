#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 模块数据表定义

复用主库连接（finfeed/news_monitor.db），新增两张独立表，不触碰 news 表：
  - llm_providers : 自定义大模型配置
  - llm_reports   : 分析报告归档

幂等创建，首次访问时自动初始化。
"""

import logging
import threading

from finfeed.storage.database import get_db_manager

logger = logging.getLogger("news_monitor")

_initialized = False
_init_lock = threading.Lock()


_DDL_PROVIDERS = """
CREATE TABLE IF NOT EXISTS llm_providers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    base_url      TEXT NOT NULL,
    api_key       TEXT DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    temperature   REAL DEFAULT 0.3,
    max_tokens    INTEGER DEFAULT 4096,
    timeout       INTEGER DEFAULT 120,
    extra_headers TEXT DEFAULT '{}',
    preset        TEXT DEFAULT 'custom',
    is_default    INTEGER DEFAULT 0,
    enabled       INTEGER DEFAULT 1,
    test_status   INTEGER DEFAULT -1,
    test_message  TEXT DEFAULT '',
    test_latency  REAL DEFAULT 0,
    test_ts       INTEGER DEFAULT 0,
    created_at    TEXT DEFAULT '',
    updated_at    TEXT DEFAULT ''
)
"""

_DDL_REPORTS = """
CREATE TABLE IF NOT EXISTS llm_reports (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id           TEXT NOT NULL DEFAULT '',
    title             TEXT NOT NULL DEFAULT '',
    provider_name     TEXT DEFAULT '',
    model             TEXT DEFAULT '',
    window_hours      INTEGER DEFAULT 24,
    scope             TEXT DEFAULT 'all',
    news_count        INTEGER DEFAULT 0,
    scanned_count     INTEGER DEFAULT 0,
    start_ts          INTEGER DEFAULT 0,
    end_ts            INTEGER DEFAULT 0,
    status            TEXT DEFAULT 'success',
    content           TEXT DEFAULT '',
    stats_json        TEXT DEFAULT '{}',
    error             TEXT DEFAULT '',
    chunk_count       INTEGER DEFAULT 0,
    prompt_tokens     INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    elapsed           REAL DEFAULT 0,
    created_at        TEXT DEFAULT '',
    created_ts        INTEGER DEFAULT 0
)
"""


def ensure_tables(force: bool = False) -> None:
    """幂等创建 LLM 模块所需数据表"""
    global _initialized
    if _initialized and not force:
        return
    with _init_lock:
        if _initialized and not force:
            return
        try:
            db = get_db_manager()
            with db.get_db() as c:
                c.execute(_DDL_PROVIDERS)
                c.execute(_DDL_REPORTS)
                c.execute(
                    "CREATE INDEX IF NOT EXISTS idx_llm_reports_ts "
                    "ON llm_reports(created_ts DESC, id DESC)"
                )
                c.execute(
                    "CREATE INDEX IF NOT EXISTS idx_llm_reports_task "
                    "ON llm_reports(task_id)"
                )
                _migrate(c)
            _initialized = True
            logger.info("LLM 模块数据表已就绪")
        except Exception as e:
            logger.error(f"LLM 模块建表失败: {e}")
            raise


def _migrate(c) -> None:
    """为早期版本补齐新增字段"""
    for table, columns in (
        ("llm_providers", [
            ("preset", "TEXT DEFAULT 'custom'"),
            ("test_latency", "REAL DEFAULT 0"),
            ("extra_headers", "TEXT DEFAULT '{}'"),
        ]),
        ("llm_reports", [
            ("scanned_count", "INTEGER DEFAULT 0"),
            ("stats_json", "TEXT DEFAULT '{}'"),
            ("chunk_count", "INTEGER DEFAULT 0"),
        ]),
    ):
        try:
            existing = {row[1] for row in c.execute(f"PRAGMA table_info({table})").fetchall()}
        except Exception:
            continue
        for col, ddl in columns:
            if col not in existing:
                try:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                    logger.info(f"LLM 表迁移：{table} 添加字段 {col}")
                except Exception as e:
                    logger.debug(f"LLM 表迁移跳过 {table}.{col}: {e}")
