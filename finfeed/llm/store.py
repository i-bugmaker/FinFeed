#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析报告持久化"""

import json
import logging
import time
from typing import Any, Dict, Optional

from finfeed.storage.database import get_db_manager
from finfeed.utils.time_utils import now_bj

from .schema import ensure_tables

logger = logging.getLogger("news_monitor")

_LIST_COLUMNS = (
    "id, task_id, title, provider_name, model, window_hours, scope, news_count, "
    "scanned_count, start_ts, end_ts, status, error, chunk_count, prompt_tokens, "
    "completion_tokens, elapsed, pinned, report_type, stock_code, "
    "created_at, created_ts"
)


def save_report(payload: Dict[str, Any]) -> int:
    """写入一份报告（成功或失败均落库），返回报告 id"""
    ensure_tables()
    now = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            """INSERT INTO llm_reports
               (task_id, title, provider_name, model, window_hours, scope, news_count,
                scanned_count, start_ts, end_ts, status, content, stats_json, error,
                chunk_count, prompt_tokens, completion_tokens, elapsed,
                report_type, stock_code, sources_json, options_json, created_at, created_ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                payload.get("task_id", ""),
                payload.get("title", ""),
                payload.get("provider_name", ""),
                payload.get("model", ""),
                int(payload.get("window_hours", 24)),
                payload.get("scope", "all"),
                int(payload.get("news_count", 0)),
                int(payload.get("scanned_count", 0)),
                int(payload.get("start_ts", 0)),
                int(payload.get("end_ts", 0)),
                payload.get("status", "success"),
                payload.get("content", ""),
                json.dumps(payload.get("stats", {}), ensure_ascii=False),
                payload.get("error", ""),
                int(payload.get("chunk_count", 0)),
                int(payload.get("prompt_tokens", 0)),
                int(payload.get("completion_tokens", 0)),
                float(payload.get("elapsed", 0)),
                payload.get("report_type", "review"),
                payload.get("stock_code", ""),
                json.dumps(payload.get("sources", []), ensure_ascii=False),
                json.dumps(payload.get("options", {}), ensure_ascii=False),
                now,
                int(time.time()),
            ),
        )
        report_id = c.lastrowid
    logger.info(
        f"LLM 分析报告已保存: id={report_id} status={payload.get('status', 'success')} "
        f"条数={payload.get('news_count', 0)}"
    )
    return report_id


def list_reports(limit: int = 50, offset: int = 0, pinned_only: bool = False) -> Dict[str, Any]:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        where = "WHERE pinned = 1" if pinned_only else ""
        c.execute(f"SELECT COUNT(*) AS cnt FROM llm_reports {where}")
        total = c.fetchone()["cnt"]
        c.execute(
            f"SELECT {_LIST_COLUMNS} FROM llm_reports {where} "
            "ORDER BY pinned DESC, created_ts DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = [dict(r) for r in c.fetchall()]
    return {"total": total, "items": rows, "limit": limit, "offset": offset}


def list_insight_history(limit: int = 20) -> Dict[str, Any]:
    """连板天地「轻量洞察」历史归档列表（report_type='limitup'），按时间倒序。"""
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT id, title, provider_name, model, created_at, created_ts "
            "FROM llm_reports WHERE report_type = 'limitup' "
            "ORDER BY created_ts DESC, id DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(r) for r in c.fetchall()]
    return {"items": rows, "limit": limit, "total": len(rows)}


def search_reports(keyword: str, limit: int = 50) -> Dict[str, Any]:
    """按标题 / 模型 / 报告正文模糊搜索"""
    ensure_tables()
    kw = f"%{keyword.strip()}%"
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT COUNT(*) AS cnt FROM llm_reports WHERE title LIKE ? OR model LIKE ? OR content LIKE ?",
                  (kw, kw, kw))
        total = c.fetchone()["cnt"]
        c.execute(
            f"SELECT {_LIST_COLUMNS} FROM llm_reports "
            "WHERE title LIKE ? OR model LIKE ? OR content LIKE ? "
            "ORDER BY pinned DESC, created_ts DESC, id DESC LIMIT ?",
            (kw, kw, kw, limit),
        )
        rows = [dict(r) for r in c.fetchall()]
    return {"total": total, "items": rows, "limit": limit}


def set_pinned(report_id: int, pinned: bool) -> bool:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("UPDATE llm_reports SET pinned = ? WHERE id = ?", (1 if pinned else 0, report_id))
        return c.rowcount > 0


def get_report(report_id: int) -> Optional[Dict[str, Any]]:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT * FROM llm_reports WHERE id = ?", (report_id,))
        row = c.fetchone()
        if not row:
            return None
        d = dict(row)
    try:
        d["stats"] = json.loads(d.get("stats_json") or "{}")
    except Exception:
        d["stats"] = {}
    d.pop("stats_json", None)
    try:
        d["sources"] = json.loads(d.get("sources_json") or "[]")
    except Exception:
        d["sources"] = []
    d.pop("sources_json", None)
    try:
        d["options"] = json.loads(d.get("options_json") or "{}")
    except Exception:
        d["options"] = {}
    d.pop("options_json", None)
    return d


def get_report_by_task(task_id: str) -> Optional[Dict[str, Any]]:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT id FROM llm_reports WHERE task_id = ? ORDER BY id DESC LIMIT 1", (task_id,))
        row = c.fetchone()
    return get_report(row["id"]) if row else None


def delete_report(report_id: int) -> bool:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("DELETE FROM llm_reports WHERE id = ?", (report_id,))
        deleted = c.rowcount
    return deleted > 0


def clear_reports() -> int:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("DELETE FROM llm_reports")
        n = c.rowcount
    return n
