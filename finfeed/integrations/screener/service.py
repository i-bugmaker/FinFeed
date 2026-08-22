#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智能选股任务执行服务。

职责：
- 管理内存任务表（状态 / 进度 / 日志 / 结果）。
- 在后台线程中执行 easy-tdx 全市场选股，实时写入进度与日志。
- 支持离线演示模式（不依赖 easy-tdx 连接）。
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from typing import Any

import pandas as pd

from finfeed.screener import (
    close,
    enrich_technical,
    fetch_universe,
    load_config,
    score_frame,
)
from finfeed.screener.models import ScreenerResult
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("screener_service")

# 任务内存表
_TASKS: dict[str, dict] = {}
_TASKS_LOCK = threading.Lock()


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


def create_task(params: dict) -> dict:
    """创建并启动一次选股任务。"""
    task = _task_template(params)
    with _TASKS_LOCK:
        _TASKS[task["task_id"]] = task
    t = threading.Thread(target=_run, args=(task,), daemon=True, name=f"screener-{task['task_id']}")
    t.start()
    return {
        "task_id": task["task_id"],
        "status": "running",
        "label": "智能选股",
    }


def get_task(task_id: str) -> dict | None:
    with _TASKS_LOCK:
        return dict(_TASKS.get(task_id, {})) if task_id in _TASKS else None


def list_tasks(limit: int = 20) -> list[dict]:
    with _TASKS_LOCK:
        items = sorted(_TASKS.values(), key=lambda x: x["started_at"], reverse=True)
        return [dict(t) for t in items[:limit]]


def _run(task: dict) -> None:
    params = task["params"] or {}
    top_n = max(1, min(int(params.get("top", 50)), 300))
    technical = bool(params.get("technical", False))
    top_tech = max(50, min(int(params.get("top_tech", 200)), 500))
    demo_mode = bool(params.get("demo", False))

    cfg = load_config()
    # 板块白名单覆盖（前端传参优先于默认配置）
    boards = params.get("boards")
    if isinstance(boards, dict):
        cfg.filters["boards"] = {k: bool(v) for k, v in boards.items()}
    try:
        _log(task, "开始选股：加载行情快照…")
        _progress(task, 5)

        if demo_mode:
            from finfeed.screener.sample_data import load_sample_dataframe

            df = load_sample_dataframe()
            _log(task, f"演示模式：使用内置 {len(df)} 条样本数据")
        else:
            df = fetch_universe(count=12000)
            _log(task, f"行情快照已加载：共 {len(df)} 只标的")

        _progress(task, 35)

        if technical:
            _log(task, f"正在为前 {top_tech} 只候选补充技术面指标…")
            df = enrich_technical(df, top_n=top_tech, kline_count=120)
            _log(task, "技术面富化完成")
            _progress(task, 70)
        else:
            _progress(task, 60)

        _log(task, "开始五维加权评分…")
        scores = score_frame(df, cfg, technical_enabled=technical)
        _progress(task, 95)

        screened_size = len(scores)
        scores = scores[:top_n]
        result = ScreenerResult(
            generated_at=now_bj().strftime("%Y-%m-%d %H:%M:%S"),
            data_source="演示数据" if demo_mode else "easy-tdx",
            snapshot_time=now_bj().strftime("%H:%M:%S"),
            universe_size=len(df),
            screened_size=screened_size,
            scored_size=len(scores),
            technical_enabled=technical,
            config_summary={
                "weights": cfg.weights,
                "filters": cfg.filters,
                "tiers": cfg.tiers,
            },
            scores=scores,
        )
        payload = result.to_dict()
        _log(task, f"评分完成：入选候选 {len(scores)} 只，评级 strong {sum(1 for s in scores if s.tier == 'strong')} / watch {sum(1 for s in scores if s.tier == 'watch')}")

        with _TASKS_LOCK:
            task["status"] = "success"
            task["result"] = payload
            task["finished_at"] = _now()
            task["progress"] = 100
    except Exception as exc:  # noqa: BLE001
        logger.exception("screener task failed")
        err = str(exc) or "未知错误"
        _log(task, f"选股失败：{err}", level="ERROR")
        _log(task, traceback.format_exc(), level="ERROR")
        with _TASKS_LOCK:
            task["status"] = "error"
            task["error"] = err
            task["finished_at"] = _now()
    finally:
        if not demo_mode:
            try:
                close()
            except Exception:  # noqa: BLE001
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
