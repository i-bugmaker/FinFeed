#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 对话会话持久化

会话与消息两张表（llm_sessions / llm_messages），复用主库连接。
前端「分析师工作区」的多会话列表、历史消息恢复均基于本模块。
"""

import logging
import time
from typing import Any, Dict, List, Optional

from finfeed.storage.database import get_db_manager
from finfeed.utils.time_utils import now_bj

from .schema import ensure_tables

logger = logging.getLogger("news_monitor")

MAX_SESSIONS = 200
MAX_MESSAGES_PER_SESSION = 400


def _now() -> int:
    return int(time.time())


def _stamp() -> str:
    return now_bj().strftime("%Y-%m-%d %H:%M:%S")


def create_session(title: str = "新会话") -> Dict[str, Any]:
    ensure_tables()
    now, ts = _stamp(), _now()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "INSERT INTO llm_sessions (title, created_at, updated_at, created_ts, updated_ts) "
            "VALUES (?,?,?,?,?)",
            (title or "新会话", now, now, ts, ts),
        )
        sid = c.lastrowid
        # 防止无限增长：超出上限时删除最旧会话
        c.execute("SELECT COUNT(*) AS cnt FROM llm_sessions")
        if c.fetchone()["cnt"] > MAX_SESSIONS:
            c.execute(
                "DELETE FROM llm_sessions WHERE id NOT IN "
                "(SELECT id FROM llm_sessions ORDER BY updated_ts DESC LIMIT ?)",
                (MAX_SESSIONS,),
            )
    return get_session(sid) or {"id": sid, "title": title or "新会话"}


def list_sessions(limit: int = 100) -> List[Dict[str, Any]]:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT id, title, created_at, updated_at, created_ts, updated_ts, "
            "(SELECT COUNT(*) FROM llm_messages m WHERE m.session_id = s.id) AS msg_count "
            "FROM llm_sessions s ORDER BY updated_ts DESC, id DESC LIMIT ?",
            (max(1, min(int(limit or 100), MAX_SESSIONS)),),
        )
        return [dict(r) for r in c.fetchall()]


def get_session(session_id: int) -> Optional[Dict[str, Any]]:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT * FROM llm_sessions WHERE id = ?", (session_id,))
        row = c.fetchone()
        return dict(row) if row else None


def rename_session(session_id: int, title: str) -> bool:
    ensure_tables()
    title = (title or "").strip()
    if not title:
        return False
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "UPDATE llm_sessions SET title = ?, updated_at = ?, updated_ts = ? WHERE id = ?",
            (title[:80], _stamp(), _now(), session_id),
        )
        return c.rowcount > 0


def delete_session(session_id: int) -> bool:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("DELETE FROM llm_messages WHERE session_id = ?", (session_id,))
        c.execute("DELETE FROM llm_sessions WHERE id = ?", (session_id,))
        return c.rowcount > 0


def touch_session(session_id: int) -> None:
    """更新会话时间戳（用于消息写入后刷新排序）"""
    try:
        db = get_db_manager()
        with db.get_db() as c:
            c.execute(
                "UPDATE llm_sessions SET updated_at = ?, updated_ts = ? WHERE id = ?",
                (_stamp(), _now(), session_id),
            )
    except Exception as e:
        logger.debug(f"touch_session 失败: {e}")


def list_messages(session_id: int) -> List[Dict[str, Any]]:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT id, role, content, created_ts FROM llm_messages "
            "WHERE session_id = ? ORDER BY id ASC LIMIT ?",
            (session_id, MAX_MESSAGES_PER_SESSION),
        )
        return [dict(r) for r in c.fetchall()]


def add_message(session_id: int, role: str, content: str) -> Optional[Dict[str, Any]]:
    ensure_tables()
    role = role if role in ("user", "assistant", "system") else "user"
    content = (content or "")[:20000]
    if not content.strip():
        return None
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "INSERT INTO llm_messages (session_id, role, content, created_ts) VALUES (?,?,?,?)",
            (session_id, role, content, _now()),
        )
        mid = c.lastrowid
        # 裁剪超长会话：仅保留最近 N 条
        c.execute(
            "DELETE FROM llm_messages WHERE session_id = ? AND id NOT IN "
            "(SELECT id FROM llm_messages WHERE session_id = ? ORDER BY id DESC LIMIT ?)",
            (session_id, session_id, MAX_MESSAGES_PER_SESSION),
        )
    touch_session(session_id)
    return {"id": mid, "session_id": session_id, "role": role, "content": content}
