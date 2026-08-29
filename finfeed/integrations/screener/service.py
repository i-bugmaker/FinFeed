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

import pandas as pd

from finfeed.screener import (
    enrich_technical,
    fetch_snapshot,
    load_config,
    score_frame,
)
from finfeed.screener import request as request_mod
from finfeed.screener.config import ScreenerConfig
from finfeed.screener.models import ScreenerResult
from finfeed.screener.snapshot_store import snapshot_store
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("screener_service")


def _enrich_growth(df: pd.DataFrame) -> pd.DataFrame:
    """为因子行注入成长性字段（东财业绩预告 earnings_forecast，is_latest=1）。

    - earnings_growth_pct：预告净利润同比增幅（取上下限均值；均为 0 时视为无数据）
    - forecast_type：预告类型（预增/扭亏/预减…）
    无覆盖的标的保持缺失（score_growth 给中性分），失败静默降级。
    """
    try:
        from finfeed.storage.database import get_db

        codes = [str(c).zfill(6) for c in df["code"].tolist()] if "code" in df.columns else []
        if not codes:
            return df
        marks = ",".join("?" for _ in codes)
        growth: dict[str, tuple] = {}
        with get_db() as c:
            rows = c.execute(
                f"""SELECT code, forecast_type, increase_low, increase_high
                    FROM earnings_forecast WHERE is_latest = 1 AND code IN ({marks})""",
                codes,
            ).fetchall()
        for r in rows:
            lo, hi = float(r["increase_low"] or 0.0), float(r["increase_high"] or 0.0)
            growth[str(r["code"]).zfill(6)] = (
                (lo + hi) / 2.0 if (lo or hi) else None,
                r["forecast_type"] or "",
            )
        if not growth:
            return df
        import math

        def _map(code):
            g = growth.get(str(code).zfill(6))
            if not g:
                return (None, "")
            return g

        mapped = df["code"].map(_map)
        df["earnings_growth_pct"] = [m[0] if m and m[0] is not None and math.isfinite(m[0]) else None
                                      for m in mapped]
        df["forecast_type"] = [m[1] if m else "" for m in mapped]
        covered = sum(1 for v in df["earnings_growth_pct"] if v is not None)
        logger.info("成长因子富化完成：覆盖 %d/%d 标的", covered, len(df))
    except Exception as exc:  # noqa: BLE001
        logger.warning("业绩预告富化失败（growth 因子按缺失处理）: %s", exc)
    return df

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
    # 结构化请求（ScreenerRequest）：用户自定义股票池 / 策略 / 输出
    req_dict = params.get("request")
    if isinstance(req_dict, dict):
        try:
            cfg = request_mod.build_config(
                request_mod.ScreenerRequest.from_dict(req_dict), load_config())
            _log(task, "已应用结构化选股请求（ScreenerRequest）")
        except Exception as exc:  # noqa: BLE001
            _log(task, f"解析选股请求失败，回退默认配置：{exc}", level="WARN")
    # 板块白名单覆盖（向后兼容旧版 RunRequest.boards 参数）
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

        df = _enrich_growth(df)
        _log(task, "开始八维加权评分…")
        engine_meta: dict = {}
        scores = score_frame(df, cfg, technical_enabled=technical,
                             store=snapshot_store, meta=engine_meta)
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
                "engine": cfg.engine,
            },
            engine_mode=engine_meta.get("engine_mode", "fixed"),
            engine_weights=engine_meta.get("engine_weights", {}),
            engine_diagnostics=engine_meta.get("engine_diagnostics", {}),
            model_status=engine_meta.get("model_status", "linear"),
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


def run_evaluation(cfg: ScreenerConfig | None = None, end_date: str | None = None,
                   horizon: int | None = None, step: int = 1) -> dict[str, Any]:
    """P6 评估闭环：对当前引擎配置做无未来函数的 walk-forward 评估。

    返回复合/分维度 RankIC、ICIR、五分位分层收益、多空价差与 IR，以及
    因子失效监控与重算触发建议（见 finfeed.screener.evaluation）。
    """
    from finfeed.screener.evaluation import evaluate_engine

    cfg = cfg or load_config()
    return evaluate_engine(cfg, snapshot_store, end_date=end_date, horizon=horizon, step=step)


# ---- 模板包装（路由层直接调用，委托 request_mod）----
def list_templates() -> list[dict]:
    return request_mod.list_templates()


def save_template(name: str, req_dict: dict) -> dict:
    return request_mod.save_template(name, req_dict)


def delete_template(name: str) -> bool:
    return request_mod.delete_template(name)


def get_config() -> dict[str, Any]:
    """返回选股方法论与配置，供前端展示与配置面板渲染。"""
    cfg = load_config()
    return {
        "weights": cfg.weights,
        "filters": cfg.filters,
        "params": cfg.params,
        "tiers": cfg.tiers,
        "neutralize": cfg.neutralize,
        "engine": cfg.engine,
        "dims": ["capital", "momentum", "valuation", "liquidity", "quality", "sentiment"],
        "dim_labels": {
            "capital": "资金面", "momentum": "动量趋势", "valuation": "估值",
            "liquidity": "量价活跃", "quality": "质量稳定", "sentiment": "情绪/事件",
        },
        "templates": request_mod.list_templates(),
        "request_schema": {
            "modes": ["linear", "ic", "auto", "ml", "blend"],
            "universe_keys": ["boards", "exclude_st", "exclude_suspended", "min_amount",
                              "min_turnover", "price_range", "pe_ttm_range", "float_cap_range",
                              "exclude_new_days"],
            "strategy_keys": ["mode", "auto_weight", "dim_weights", "orthogonalize",
                              "blend_alpha", "ml"],
            "output_keys": ["top", "tiers", "with_technical", "with_factor_exposure"],
        },
        "methodology": cfg.explain(),
    }


def _execute_once(cfg: ScreenerConfig, df: pd.DataFrame, technical: bool,
                  top_n: int = 200) -> ScreenerResult:
    """单次评分 + 结果封装（供 compare 复用，不写任务状态）。"""
    df = _enrich_growth(df)
    engine_meta: dict = {}
    scores = score_frame(df, cfg, technical_enabled=technical,
                         store=snapshot_store, meta=engine_meta)
    scores = scores[:top_n]
    return ScreenerResult(
        generated_at=now_bj().strftime("%Y-%m-%d %H:%M:%S"),
        data_source="compare",
        snapshot_time="",
        as_of_kind="local",
        fallback_chain=[],
        coverage=1.0,
        universe_size=len(df),
        screened_size=len(scores),
        scored_size=len(scores),
        technical_enabled=technical,
        config_summary={"weights": cfg.weights, "engine": cfg.engine},
        engine_mode=engine_meta.get("engine_mode", "fixed"),
        engine_weights=engine_meta.get("engine_weights", {}),
        engine_diagnostics=engine_meta.get("engine_diagnostics", {}),
        model_status=engine_meta.get("model_status", "linear"),
        scores=scores,
    )


def run_compare(req_a: dict, req_b: dict, technical: bool = False,
                top_n: int = 200) -> dict[str, Any]:
    """策略对比：同一快照下跑两套规则，返回结果与差异摘要。"""
    cfg_a = request_mod.build_config(request_mod.ScreenerRequest.from_dict(req_a or {}), load_config())
    cfg_b = request_mod.build_config(request_mod.ScreenerRequest.from_dict(req_b or {}), load_config())
    bundle = fetch_snapshot(count=12000)
    df = bundle.df
    if technical:
        df, _ = enrich_technical(df, top_n=top_n, kline_count=120)
    ra = _execute_once(cfg_a, df, technical, top_n)
    rb = _execute_once(cfg_b, df, technical, top_n)
    sa = {s.code for s in ra.scores if s.tier in ("strong", "watch")}
    sb = {s.code for s in rb.scores if s.tier in ("strong", "watch")}
    union = sa | sb
    return {
        "a": ra.to_dict(),
        "b": rb.to_dict(),
        "delta": {
            "summary_a": request_mod.summarize_result(ra),
            "summary_b": request_mod.summarize_result(rb),
            "overlap_strong_watch": len(sa & sb),
            "jaccard": round(len(sa & sb) / len(union), 4) if union else None,
        },
        "config_diff": request_mod.compare_configs(cfg_a, cfg_b),
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
