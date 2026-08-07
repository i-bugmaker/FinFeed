#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日历模块数据表定义

复用主库连接（finfeed/news_monitor.db），新增两张独立表，不触碰 news 表：
  - calendar_events : 归一化后的日历事件
  - calendar_sync   : 按「类型 + 日期」记录同步水位，用于 TTL 增量刷新

幂等创建，首次访问时自动初始化。
"""

import logging
import threading

from finfeed.storage.database import get_db_manager

logger = logging.getLogger("news_monitor")

_initialized = False
_init_lock = threading.Lock()


_DDL_EVENTS = """
CREATE TABLE IF NOT EXISTS calendar_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    cal_type       TEXT    NOT NULL,
    event_key      TEXT    NOT NULL,
    event_date     TEXT    NOT NULL,
    end_date       TEXT    DEFAULT '',
    event_time     TEXT    DEFAULT '',
    category       TEXT    DEFAULT '',
    sub_type       TEXT    DEFAULT '',
    title          TEXT    NOT NULL DEFAULT '',
    content        TEXT    DEFAULT '',
    code           TEXT    DEFAULT '',
    name           TEXT    DEFAULT '',
    region         TEXT    DEFAULT '',
    importance     INTEGER DEFAULT 0,
    period         TEXT    DEFAULT '',
    prev_value     TEXT    DEFAULT '',
    forecast_value TEXT    DEFAULT '',
    actual_value   TEXT    DEFAULT '',
    url            TEXT    DEFAULT '',
    extra          TEXT    DEFAULT '{}',
    updated_ts     INTEGER DEFAULT 0,
    UNIQUE(cal_type, event_date, event_key)
)
"""

_DDL_SYNC = """
CREATE TABLE IF NOT EXISTS calendar_sync (
    cal_type   TEXT    NOT NULL,
    sync_date  TEXT    NOT NULL,
    updated_ts INTEGER DEFAULT 0,
    row_count  INTEGER DEFAULT 0,
    status     TEXT    DEFAULT 'ok',
    err        TEXT    DEFAULT '',
    PRIMARY KEY (cal_type, sync_date)
)
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_cal_type_date "
    "ON calendar_events(cal_type, event_date, importance DESC, id)",

    "CREATE INDEX IF NOT EXISTS idx_cal_date "
    "ON calendar_events(event_date, cal_type)",

    "CREATE INDEX IF NOT EXISTS idx_cal_category "
    "ON calendar_events(cal_type, category, event_date)",

    "CREATE INDEX IF NOT EXISTS idx_cal_code "
    "ON calendar_events(code, event_date)",

    "CREATE INDEX IF NOT EXISTS idx_cal_region "
    "ON calendar_events(region, event_date)",

    "CREATE INDEX IF NOT EXISTS idx_cal_sync_ts "
    "ON calendar_sync(cal_type, sync_date, updated_ts)",
)


def ensure_tables(force: bool = False) -> None:
    """幂等创建日历模块所需数据表"""
    global _initialized
    if _initialized and not force:
        return
    with _init_lock:
        if _initialized and not force:
            return
        try:
            db = get_db_manager()
            with db.get_db() as c:
                c.execute(_DDL_EVENTS)
                c.execute(_DDL_SYNC)
                for ddl in _INDEXES:
                    c.execute(ddl)
            _initialized = True
            logger.info("日历模块数据表已就绪")
        except Exception as e:
            logger.error(f"日历模块建表失败: {e}")
            raise


def reset_tables() -> None:
    """清空日历数据（调试用）"""
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("DELETE FROM calendar_events")
        c.execute("DELETE FROM calendar_sync")
    logger.info("日历数据已清空")
