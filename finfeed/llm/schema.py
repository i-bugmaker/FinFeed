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
    pinned            INTEGER DEFAULT 0,
    report_type       TEXT DEFAULT 'review',
    stock_code        TEXT DEFAULT '',
    sources_json      TEXT DEFAULT '[]',
    options_json      TEXT DEFAULT '{}',
    created_at        TEXT DEFAULT '',
    created_ts        INTEGER DEFAULT 0
)
"""

_DDL_SETTINGS = """
CREATE TABLE IF NOT EXISTS llm_settings (
    key    TEXT PRIMARY KEY,
    value  TEXT DEFAULT ''
)
"""

_DDL_SESSIONS = """
CREATE TABLE IF NOT EXISTS llm_sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL DEFAULT '新会话',
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT '',
    created_ts INTEGER DEFAULT 0,
    updated_ts INTEGER DEFAULT 0
)
"""

_DDL_MESSAGES = """
CREATE TABLE IF NOT EXISTS llm_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    role       TEXT NOT NULL DEFAULT 'user',
    content    TEXT DEFAULT '',
    created_ts INTEGER DEFAULT 0
)
"""

_DDL_AGENTS = """
CREATE TABLE IF NOT EXISTS llm_agents (
    agent_key      TEXT PRIMARY KEY,
    name           TEXT DEFAULT '',
    personality    TEXT DEFAULT '',
    stance         TEXT DEFAULT '',
    style          TEXT DEFAULT '',
    tone           TEXT DEFAULT '',
    system_prompt  TEXT DEFAULT '',
    updated_ts     INTEGER DEFAULT 0
)
"""

# 智能体默认画像（供 ensure_tables 幂等播种；对应 REPORT_TYPES 与自由问答 chat）
# 各字段为"建议性默认"，system_prompt 留空则运行时取 DEFAULT_PROMPTS 对应 *_system。
_AGENT_DEFAULTS: dict = {
    "flash": {
        "name": "快讯分析师",
        "personality": "理性审慎、消息驱动、多空平衡",
        "stance": "平衡（利好利空同等对待）",
        "style": "精准聚焦、结论先行",
        "tone": "专业",
    },
    "review": {
        "name": "市场策略师",
        "personality": "全面系统、逻辑严密、数据为重",
        "stance": "平衡（全市场多空研判）",
        "style": "深度复盘、结构化",
        "tone": "专业",
    },
    "stock": {
        "name": "个股研究员",
        "personality": "严谨细致、重基本面与风险",
        "stance": "中性（研究与风险并重）",
        "style": "深度、可追溯",
        "tone": "专业",
    },
    "sentiment": {
        "name": "舆情分析师",
        "personality": "敏锐、注重情绪与热度信号",
        "stance": "中性",
        "style": "研判、预警导向",
        "tone": "亲和",
    },
    "chat": {
        "name": "财经助手",
        "personality": "耐心、清晰、客观",
        "stance": "中立",
        "style": "简洁、要点化",
        "tone": "亲和",
    },
}


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
                c.execute(_DDL_SETTINGS)
                c.execute(_DDL_SESSIONS)
                c.execute(_DDL_MESSAGES)
                c.execute(_DDL_AGENTS)
                c.execute(
                    "CREATE INDEX IF NOT EXISTS idx_llm_reports_ts "
                    "ON llm_reports(created_ts DESC, id DESC)"
                )
                c.execute(
                    "CREATE INDEX IF NOT EXISTS idx_llm_reports_task "
                    "ON llm_reports(task_id)"
                )
                c.execute(
                    "CREATE INDEX IF NOT EXISTS idx_llm_messages_session "
                    "ON llm_messages(session_id, id)"
                )
                _seed_agents(c)
                _migrate(c)
            _initialized = True
            logger.info("LLM 模块数据表已就绪")
        except Exception as e:
            logger.error(f"LLM 模块建表失败: {e}")
            raise


def _seed_agents(c) -> None:
    """播种智能体默认画像：仅在缺失 agent 时插入默认行，不覆盖用户已改配置。"""
    for key, fields in _AGENT_DEFAULTS.items():
        try:
            c.execute(
                "INSERT OR IGNORE INTO llm_agents (agent_key, name, personality, stance, style, tone, updated_ts) "
                "VALUES (?,?,?,?,?,?,0)",
                (key, fields.get("name", ""), fields.get("personality", ""),
                 fields.get("stance", ""), fields.get("style", ""), fields.get("tone", "")),
            )
        except Exception as e:  # noqa: BLE001 —— 播种异常不影响主流程
            logger.debug(f"播种智能体 {key} 失败: {e}")


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
            ("pinned", "INTEGER DEFAULT 0"),
            ("report_type", "TEXT DEFAULT 'review'"),
            ("stock_code", "TEXT DEFAULT ''"),
            ("sources_json", "TEXT DEFAULT '[]'"),
            ("options_json", "TEXT DEFAULT '{}'"),
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
