#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股运行审计（数据质量可观测性）。

记录每次选股运行的关键指标到 SQLite（screener_runs 表）：
    数据源 / 回退链 / 快照时间 / 覆盖率 / 各阶段数量 / 耗时 / 错误码。

供数据质量监控、故障排查与后续回测校准使用。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("finfeed.screener.audit")

_AUDIT_DB = Path(__file__).resolve().parent.parent.parent / "logs" / "screener_audit.db"


class RunAudit:
    """选股运行审计表。"""

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = str(db_path or _AUDIT_DB)
        self._lock = threading.Lock()
        self._init()

    def _init(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(self._path, timeout=10)
            try:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS screener_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        generated_at TEXT,
                        source TEXT,
                        fallback_chain TEXT,
                        as_of TEXT,
                        as_of_kind TEXT,
                        coverage REAL,
                        universe_size INTEGER,
                        screened_size INTEGER,
                        scored_size INTEGER,
                        strong_count INTEGER,
                        technical_enabled INTEGER,
                        duration_ms INTEGER,
                        error_code TEXT,
                        error_msg TEXT
                    )"""
                )
                conn.commit()
            finally:
                conn.close()

    def record(self, run: dict[str, Any]) -> None:
        """写入一次运行记录。"""
        try:
            with self._lock:
                conn = sqlite3.connect(self._path, timeout=10)
                try:
                    conn.execute(
                        """INSERT INTO screener_runs
                           (generated_at, source, fallback_chain, as_of, as_of_kind,
                            coverage, universe_size, screened_size, scored_size,
                            strong_count, technical_enabled, duration_ms,
                            error_code, error_msg)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            run.get("generated_at", ""),
                            run.get("source", ""),
                            ",".join(run.get("fallback_chain") or []) if len(run.get("fallback_chain") or []) > 1 else "",
                            run.get("as_of", ""),
                            run.get("as_of_kind", ""),
                            float(run.get("coverage", 1.0)),
                            int(run.get("universe_size", 0)),
                            int(run.get("screened_size", 0)),
                            int(run.get("scored_size", 0)),
                            int(run.get("strong_count", 0)),
                            1 if run.get("technical_enabled") else 0,
                            int(run.get("duration_ms", 0)),
                            run.get("error_code"),
                            run.get("error_msg"),
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
        except sqlite3.Error as exc:
            logger.warning("审计写入失败: %s", exc)

    def recent(self, limit: int = 20) -> list[dict]:
        """最近运行记录（供健康面板/监控查询）。"""
        try:
            conn = sqlite3.connect(self._path, timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT * FROM screener_runs ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()
        except sqlite3.Error:
            return []

    def summary(self) -> dict[str, Any]:
        """聚合摘要：运行次数、成功率、平均覆盖率、回退次数。"""
        try:
            conn = sqlite3.connect(self._path, timeout=10)
            try:
                total = conn.execute("SELECT COUNT(*) FROM screener_runs").fetchone()[0]
                if total == 0:
                    return {"runs": 0}
                err = conn.execute("SELECT COUNT(*) FROM screener_runs WHERE error_code IS NOT NULL").fetchone()[0]
                fb = conn.execute("SELECT COUNT(*) FROM screener_runs WHERE fallback_chain != ''").fetchone()[0]
                avg_cov = conn.execute("SELECT AVG(coverage) FROM screener_runs").fetchone()[0] or 0.0
                avg_ms = conn.execute("SELECT AVG(duration_ms) FROM screener_runs").fetchone()[0] or 0.0
                return {
                    "runs": int(total),
                    "success_rate": round(1.0 - err / total, 4),
                    "fallback_rate": round(fb / total, 4),
                    "avg_coverage": round(float(avg_cov), 4),
                    "avg_duration_ms": int(avg_ms),
                }
            finally:
                conn.close()
        except sqlite3.Error:
            return {"runs": 0}


audit = RunAudit()
