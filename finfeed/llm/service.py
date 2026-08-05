#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析任务调度

在独立守护线程中执行分析，主 HTTP 线程只做任务提交与进度查询。
同一进程内同时只允许一个分析任务运行（LLM 调用昂贵且串行更可控）。
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from . import analyzer, collector, config as cfg, store
from .analyzer import AnalysisCancelled
from .client import LLMError, build_client

logger = logging.getLogger("news_monitor")

MAX_TASK_HISTORY = 20

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

STAGE_LABELS = {
    "queued": "排队中",
    "collect": "检索新闻库",
    "stats": "统计计算",
    "chunk": "分批准备",
    "map": "批次压缩",
    "reduce": "汇总成文",
    "assemble": "拼装报告",
    "done": "已完成",
}


@dataclass
class TaskState:
    task_id: str
    status: str = STATUS_PENDING
    stage: str = "queued"
    stage_label: str = "排队中"
    progress: float = 0.0
    message: str = "任务已创建"
    hours: int = 24
    scope: str = "all"
    provider_name: str = ""
    model: str = ""
    news_count: int = 0
    scanned_count: int = 0
    chunk_count: int = 0
    report_id: int = 0
    error: str = ""
    error_kind: str = ""
    created_ts: float = field(default_factory=time.time)
    started_ts: float = 0.0
    finished_ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["elapsed"] = round(
            (self.finished_ts or time.time()) - (self.started_ts or self.created_ts), 1
        )
        return d


class AnalysisService:
    """分析任务管理器（单例）"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: Dict[str, TaskState] = {}
        self._order: List[str] = []
        self._active_id: Optional[str] = None
        self._cancel_flags: Dict[str, bool] = {}

    # ---------- 查询 ----------
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            t = self._tasks.get(task_id)
            return t.to_dict() if t else None

    def get_active(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if self._active_id and self._active_id in self._tasks:
                return self._tasks[self._active_id].to_dict()
            return None

    def list_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            ids = self._order[-limit:][::-1]
            return [self._tasks[i].to_dict() for i in ids if i in self._tasks]

    def is_busy(self) -> bool:
        with self._lock:
            if not self._active_id:
                return False
            t = self._tasks.get(self._active_id)
            return bool(t and t.status in (STATUS_PENDING, STATUS_RUNNING))

    # ---------- 控制 ----------
    def cancel(self, task_id: str) -> bool:
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t.status not in (STATUS_PENDING, STATUS_RUNNING):
                return False
            self._cancel_flags[task_id] = True
            t.message = "正在取消…"
        return True

    def submit(self, options: Dict[str, Any]) -> Dict[str, Any]:
        """提交分析任务。返回 {ok, task_id, error}"""
        if self.is_busy():
            active = self.get_active()
            return {
                "ok": False,
                "error": "已有分析任务正在运行，请等待完成或先取消",
                "active": active,
            }

        provider_id = options.get("provider_id")
        provider = None
        if provider_id:
            try:
                provider = cfg.get_provider(int(provider_id))
            except (TypeError, ValueError):
                provider = None
        if provider is None:
            provider = cfg.get_default_provider()
        if provider is None:
            return {"ok": False, "error": "尚未配置任何大语言模型，请先在上方添加并测试连通性"}
        if not provider.enabled:
            return {"ok": False, "error": f"配置「{provider.name}」已被禁用"}

        task_id = uuid.uuid4().hex[:16]
        hours = collector.normalize_window(options.get("hours", 24))
        scope = options.get("scope") or collector.SCOPE_ALL
        if scope not in collector.SCOPES:
            scope = collector.SCOPE_ALL

        state = TaskState(
            task_id=task_id,
            status=STATUS_PENDING,
            hours=hours,
            scope=scope,
            provider_name=provider.name,
            model=provider.model,
        )
        with self._lock:
            self._tasks[task_id] = state
            self._order.append(task_id)
            self._cancel_flags[task_id] = False
            self._active_id = task_id
            while len(self._order) > MAX_TASK_HISTORY:
                old = self._order.pop(0)
                self._tasks.pop(old, None)
                self._cancel_flags.pop(old, None)

        thread = threading.Thread(
            target=self._run,
            args=(task_id, provider, options),
            daemon=True,
            name=f"llm-analysis-{task_id}",
        )
        thread.start()
        logger.info(f"LLM 分析任务已提交: {task_id} 窗口={hours}h 范围={scope} 模型={provider.model}")
        return {"ok": True, "task_id": task_id, "task": state.to_dict()}

    # ---------- 执行 ----------
    def _update(self, task_id: str, **kwargs) -> None:
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return
            for k, v in kwargs.items():
                if hasattr(t, k):
                    setattr(t, k, v)
            if "stage" in kwargs:
                t.stage_label = STAGE_LABELS.get(kwargs["stage"], kwargs["stage"])

    def _should_cancel(self, task_id: str) -> bool:
        with self._lock:
            return bool(self._cancel_flags.get(task_id))

    def _run(self, task_id: str, provider, options: Dict[str, Any]) -> None:
        self._update(task_id, status=STATUS_RUNNING, started_ts=time.time(),
                     stage="collect", progress=1, message="任务启动中…")

        def _num(key, cast, default, lo=None, hi=None):
            try:
                v = cast(options.get(key, default))
            except (TypeError, ValueError):
                v = default
            if lo is not None:
                v = max(lo, v)
            if hi is not None:
                v = min(hi, v)
            return v

        try:
            client = build_client(provider)

            def on_progress(stage: str, pct: float, msg: str):
                self._update(task_id, stage=stage, progress=round(pct, 1), message=msg)

            result = analyzer.run_analysis(
                client,
                hours=collector.normalize_window(options.get("hours", 24)),
                scope=options.get("scope") or collector.SCOPE_ALL,
                min_importance=_num("min_importance", float, 0.0, 0.0, 10.0),
                max_items=_num("max_items", int, 500, 20, 5000),
                order=options.get("order") or collector.ORDER_IMPORTANCE,
                chunk_chars=_num("chunk_chars", int, 8000, 2000, 40000),
                max_chunks=_num("max_chunks", int, 20, 1, 60),
                focus=str(options.get("focus") or ""),
                progress=on_progress,
                should_cancel=lambda: self._should_cancel(task_id),
            )

            report_id = store.save_report({
                "task_id": task_id,
                "title": result["title"],
                "provider_name": provider.name,
                "model": result["model"],
                "window_hours": result["window_hours"],
                "scope": result["scope"],
                "news_count": result["news_count"],
                "scanned_count": result["scanned_count"],
                "start_ts": result["start_ts"],
                "end_ts": result["end_ts"],
                "status": "success",
                "content": result["content"],
                "stats": result["stats"],
                "chunk_count": result["chunk_count"],
                "prompt_tokens": result["prompt_tokens"],
                "completion_tokens": result["completion_tokens"],
                "elapsed": result["elapsed"],
            })

            self._update(
                task_id, status=STATUS_SUCCESS, stage="done", progress=100,
                message=f"分析完成，共归纳 {result['news_count']} 条资讯",
                news_count=result["news_count"], scanned_count=result["scanned_count"],
                chunk_count=result["chunk_count"], report_id=report_id,
                finished_ts=time.time(),
            )
            logger.info(f"LLM 分析任务完成: {task_id} report_id={report_id}")

        except AnalysisCancelled:
            self._update(task_id, status=STATUS_CANCELLED, stage="done", progress=100,
                         message="任务已取消", finished_ts=time.time())
            logger.info(f"LLM 分析任务被取消: {task_id}")
        except LLMError as e:
            self._update(task_id, status=STATUS_FAILED, stage="done", progress=100,
                         message=e.message, error=e.message, error_kind=e.kind,
                         finished_ts=time.time())
            logger.warning(f"LLM 分析任务失败: {task_id} - {e.message}")
        except Exception as e:
            msg = f"{type(e).__name__}: {str(e)[:200]}"
            self._update(task_id, status=STATUS_FAILED, stage="done", progress=100,
                         message=msg, error=msg, error_kind="unknown",
                         finished_ts=time.time())
            logger.error(f"LLM 分析任务异常: {task_id} - {msg}", exc_info=True)
        finally:
            with self._lock:
                if self._active_id == task_id:
                    self._active_id = None


_service: Optional[AnalysisService] = None
_service_lock = threading.Lock()


def get_service() -> AnalysisService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = AnalysisService()
    return _service
