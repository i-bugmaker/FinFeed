#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智能选股任务执行服务。

职责：
- 管理内存任务表（状态 / 进度 / 日志 / 结果）。
- 在后台线程中执行多源选股（easy-tdx 实时 → 东财 datacenter 回退），实时写入进度与日志。
- 任务并发上限 1（TDX 单连接被全局调用锁串行化，并发无收益且互相拖慢）；
  相同参数的去重提交直接复用进行中任务。
- 数据仅来自真实市场数据源，不含任何演示数据。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from finfeed.screener import (
    enrich_technical,
    fetch_snapshot,
    load_config,
    score_frame,
)
from finfeed.screener.models import ScreenerResult
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("screener_service")

# 任务内存表（当前进程；历史任务从 TaskStore 恢复）
_TASKS: dict[str, dict] = {}
_TASKS_LOCK = threading.Lock()

# 并发上限：TDX 单连接 + 全局调用锁，串行执行收益最高
MAX_CONCURRENT = 1

_TASK_DB = Path(__file__).resolve().parent.parent.parent / "logs" / "screener_tasks.db"


class TaskStore:
    """任务持久化（SQLite）：进程重启后任务与结果可恢复。

    写入策略：创建 / 成功 / 失败 三个节点落库（进度高频更新仅走内存）。
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = str(db_path or _TASK_DB)
        self._lock = threading.Lock()
        self._init()

    def _conn(self):
        """每次操作独立连接，用后自动关闭；正常退出提交、异常回滚。"""
        from contextlib import contextmanager

        @contextmanager
        def _open():
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._path, check_same_thread=False, timeout=10)
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return _open()

    def _init(self) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS screener_tasks (
                    task_id TEXT PRIMARY KEY,
                    params TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER,
                    logs TEXT,
                    result TEXT,
                    error TEXT,
                    started_at REAL,
                    finished_at REAL
                )"""
            )

    def save(self, task: dict) -> None:
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO screener_tasks
                       (task_id, params, status, progress, logs, result, error,
                        started_at, finished_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        task["task_id"],
                        json.dumps(task.get("params") or {}, ensure_ascii=False),
                        task.get("status", "running"),
                        task.get("progress", 0),
                        json.dumps(task.get("logs") or [], ensure_ascii=False),
                        json.dumps(task.get("result"), ensure_ascii=False) if task.get("result") else None,
                        task.get("error"),
                        task.get("started_at", 0.0),
                        task.get("finished_at"),
                    ),
                )
        except sqlite3.Error as exc:
            logger.warning("任务持久化失败 %s: %s", task.get("task_id"), exc)

    def load(self, task_id: str) -> dict | None:
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM screener_tasks WHERE task_id=?", (task_id,)
                ).fetchone()
            return self._row_to_task(row) if row else None
        except sqlite3.Error:
            return None

    def recent(self, limit: int = 20) -> list[dict]:
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM screener_tasks ORDER BY started_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [self._row_to_task(r) for r in rows if r]
        except sqlite3.Error:
            return []

    @staticmethod
    def _row_to_task(row: sqlite3.Row | tuple) -> dict:
        def g(k: str):
            try:
                return row[k] if isinstance(row, sqlite3.Row) else dict(zip(
                    ["task_id", "params", "status", "progress", "logs", "result",
                     "error", "started_at", "finished_at"], row))[k]
            except Exception:  # noqa: BLE001
                return None

        def jload(v):
            if not v:
                return None
            try:
                return json.loads(v)
            except (TypeError, ValueError):
                return None

        return {
            "task_id": g("task_id"),
            "func_id": "screener.run",
            "func_label": "智能选股",
            "params": jload(g("params")) or {},
            "status": g("status"),
            "progress": g("progress") or 0,
            "logs": jload(g("logs")) or [],
            "result": jload(g("result")),
            "error": g("error"),
            "started_at": g("started_at") or 0.0,
            "finished_at": g("finished_at"),
        }


_store = TaskStore()


def _now() -> float:
    return time.time()


def _log(task: dict, msg: str, level: str = "INFO") -> None:
    with _TASKS_LOCK:
        task["logs"].append({"t": _now(), "level": level, "msg": msg})
        if len(task["logs"]) > 500:
            task["logs"] = task["logs"][-500:]


def _progress(task: dict, pct: int) -> None:
    with _TASKS_LOCK:
        task["progress"] = max(0, min(100, pct))


def _task_template(params: dict) -> dict:
    task_id = uuid.uuid4().hex[:12]
    return {
        "task_id": task_id,
        "func_id": "screener.run",
        "func_label": "智能选股",
        "params": params,
        "status": "running",
        "progress": 0,
        "logs": [],
        "result": None,
        "error": None,
        "started_at": _now(),
        "finished_at": None,
    }


def _params_fingerprint(params: dict) -> tuple:
    """参数指纹（用于去重）：仅比对影响结果的参数。"""
    return (
        int(params.get("top", 50)),
        bool(params.get("technical", False)),
        int(params.get("top_tech", 200)),
        tuple(sorted((params.get("boards") or {}).items())),
    )


def _running_tasks() -> list[dict]:
    with _TASKS_LOCK:
        return [t for t in _TASKS.values() if t["status"] == "running"]


def create_task(params: dict) -> dict:
    """创建并启动一次选股任务（并发上限 1；同参去重复用）。"""
    running = _running_tasks()
    if running:
        fp = _params_fingerprint(params)
        for t in running:
            if _params_fingerprint(t["params"] or {}) == fp:
                return {"task_id": t["task_id"], "status": "running", "label": "智能选股", "reused": True}
        raise RuntimeError("已有选股任务进行中，请等待完成后再提交")

    task = _task_template(params)
    with _TASKS_LOCK:
        _TASKS[task["task_id"]] = task
    _store.save(task)
    t = threading.Thread(target=_run, args=(task,), daemon=True, name=f"screener-{task['task_id']}")
    t.start()
    return {
        "task_id": task["task_id"],
        "status": "running",
        "label": "智能选股",
    }


def get_task(task_id: str) -> dict | None:
    with _TASKS_LOCK:
        t = _TASKS.get(task_id)
    if t is not None:
        return dict(t)
    # 内存未命中（进程重启后）：从持久化存储恢复
    return _store.load(task_id)


def list_tasks(limit: int = 20) -> list[dict]:
    with _TASKS_LOCK:
        mem = [dict(t) for t in _TASKS.values()]
    recent = _store.recent(limit)
    seen = {t["task_id"] for t in mem}
    merged = mem + [t for t in recent if t["task_id"] not in seen]
    merged.sort(key=lambda x: x.get("started_at") or 0.0, reverse=True)
    return merged[:limit]


def _run(task: dict) -> None:
    params = task["params"] or {}
    top_n = max(1, min(int(params.get("top", 50)), 300))
    technical = bool(params.get("technical", False))
    top_tech = max(50, min(int(params.get("top_tech", 200)), 500))

    cfg = load_config()
    # 板块白名单覆盖（前端传参优先于默认配置）
    boards = params.get("boards")
    if isinstance(boards, dict):
        cfg.filters["boards"] = {k: bool(v) for k, v in boards.items()}
    start = _now()
    try:
        _log(task, "开始选股：加载行情快照…")
        _progress(task, 5)

        bundle = fetch_snapshot(count=12000)
        df = bundle.df
        _log(task, f"行情快照已加载：共 {len(df)} 只标的，来源 {bundle.describe()}（as_of={bundle.as_of}）")

        _progress(task, 35)

        tech_coverage = 0.0
        if technical:
            _log(task, f"正在为前 {top_tech} 只候选补充技术面指标…")
            df, tech_coverage = enrich_technical(df, top_n=top_tech, kline_count=120)
            _log(task, f"技术面富化完成（覆盖率 {tech_coverage:.0%}）")
            _progress(task, 70)
        else:
            _progress(task, 60)

        _log(task, "开始五维加权评分…")
        scores = score_frame(df, cfg, technical_enabled=technical)
        _progress(task, 95)

        screened_size = len(scores)
        scored_size = screened_size
        scores = scores[:top_n]
        result = ScreenerResult(
            generated_at=now_bj().strftime("%Y-%m-%d %H:%M:%S"),
            data_source=bundle.describe(),
            snapshot_time=bundle.as_of,
            as_of_kind=bundle.as_of_kind,
            fallback_chain=bundle.fallback_chain,
            coverage=round(bundle.coverage * (tech_coverage if technical else 1.0), 4),
            universe_size=len(df),
            screened_size=screened_size,
            scored_size=scored_size,
            technical_enabled=technical,
            config_summary={
                "weights": cfg.weights,
                "filters": cfg.filters,
                "tiers": cfg.tiers,
            },
            scores=scores,
        )
        payload = result.to_dict()
        strong_count = sum(1 for s in scores if s.tier == "strong")
        _log(task, f"评分完成：入选候选 {len(scores)} 只，评级 strong {strong_count} / watch {sum(1 for s in scores if s.tier == 'watch')}")

        with _TASKS_LOCK:
            task["status"] = "success"
            task["result"] = payload
            task["finished_at"] = _now()
            task["progress"] = 100
        _store.save(task)
        _record_audit(result, strong_count, start, error_code=None)
    except Exception as exc:  # noqa: BLE001
        logger.exception("screener task failed")
        err = str(exc) or "未知错误"
        _log(task, f"选股失败：{err}", level="ERROR")
        _log(task, traceback.format_exc(), level="ERROR")
        with _TASKS_LOCK:
            task["status"] = "error"
            task["error"] = err
            task["error_code"] = _error_code_of(exc)
            task["finished_at"] = _now()
        _store.save(task)
        _record_audit(None, 0, start, error_code=_error_code_of(exc), error_msg=err)
    finally:
        # 注意：不在此处关闭全局 TDX 连接 —— 该连接为进程级单例，
        # 与资金流大屏等模块共享，主动关闭会误伤并发活跃请求；
        # 连接由 ensure_alive 自动重连，进程退出时自然回收。
        pass


def get_config() -> dict[str, Any]:
    """返回选股方法论与配置，供前端展示。"""
    cfg = load_config()
    return {
        "weights": cfg.weights,
        "filters": cfg.filters,
        "params": cfg.params,
        "tiers": cfg.tiers,
        "neutralize": cfg.neutralize,
        "methodology": cfg.explain(),
    }


def _error_code_of(exc: Exception) -> str:
    """把异常映射为结构化错误码（前端据此展示可读提示）。"""
    name = type(exc).__name__
    if name in ("DataSourceError", "RuntimeError"):
        return "SOURCE_UNAVAILABLE"
    if name in ("TimeoutError", "ConnectionError"):
        return "TIMEOUT"
    return "UNKNOWN"


def _record_audit(result: ScreenerResult | None, strong_count: int,
                  start: float, error_code: str | None, error_msg: str | None = None) -> None:
    """写入运行审计（screener_runs 表，供数据质量监控）。"""
    from finfeed.screener.audit import audit

    try:
        audit.record({
            "generated_at": result.generated_at if result else now_bj().strftime("%Y-%m-%d %H:%M:%S"),
            "source": result.data_source if result else "",
            "fallback_chain": result.fallback_chain if result else [],
            "as_of": result.snapshot_time if result else "",
            "as_of_kind": result.as_of_kind if result else "",
            "coverage": result.coverage if result else 0.0,
            "universe_size": result.universe_size if result else 0,
            "screened_size": result.screened_size if result else 0,
            "scored_size": result.scored_size if result else 0,
            "strong_count": strong_count,
            "technical_enabled": result.technical_enabled if result else False,
            "duration_ms": int((_now() - start) * 1000),
            "error_code": error_code,
            "error_msg": (error_msg or "")[:500],
        })
    except Exception:  # noqa: BLE001
        logger.warning("审计记录失败", exc_info=True)
