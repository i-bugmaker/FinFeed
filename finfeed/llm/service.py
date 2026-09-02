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
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import analyzer, collector, store
from . import config as cfg
from . import prompts as analyzer_prompts
from .analyzer import AnalysisCancelled
from .client import LLMError, build_client

logger = logging.getLogger("news_monitor")

MAX_TASK_HISTORY = 20
MAX_QUEUE_SIZE = 5  # 运行中之外的排队任务上限（超出返回 409）

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
    report_type: str = "review"
    stock_code: str = ""
    provider_name: str = ""
    model: str = ""
    news_count: int = 0
    scanned_count: int = 0
    chunk_count: int = 0
    report_id: int = 0
    error: str = ""
    error_kind: str = ""
    options: Dict[str, Any] = field(default_factory=dict)
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
        self._queue: List[str] = []  # 排队任务（FIFO）
        self._active_id: Optional[str] = None
        self._cancel_flags: Dict[str, bool] = {}
        # 任务事件发布器：fn(task_id, payload)，由传输层（SSE）注入；领域层不感知 UI。
        self._publisher: Optional[Callable[[str, Dict[str, Any]], None]] = None

    # ---------- 事件发布 ----------
    def set_event_publisher(self, fn: Optional[Callable[[str, Dict[str, Any]], None]]) -> None:
        """注入/移除任务事件发布器（线程安全；None 表示关闭发布）。"""
        with self._lock:
            self._publisher = fn

    def _publish(self, task_id: str, **payload: Any) -> None:
        fn = self._publisher
        if fn is None:
            return
        try:
            fn(task_id, {"task_id": task_id, **payload})
        except Exception as e:  # noqa: BLE001 —— 订阅方异常绝不影响分析主流程
            logger.debug(f"LLM 任务事件发布失败: {e}")

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
        """任务列表 = 实时内存任务 + 数据库已落库报告。

        历史任务（服务重启 / 超出 MAX_TASK_HISTORY 内存上限）从 llm_reports 表恢复，
        保证任务中心不丢失已有数据；内存中的进行中/排队/最近完成任务覆盖同名记录。
        """
        result: Dict[str, Dict[str, Any]] = {}
        # 1) 实时内存任务为主，保证显示最新状态
        with self._lock:
            for i in self._order[::-1]:
                t = self._tasks.get(i)
                if t:
                    result[i] = t.to_dict()
        # 2) 数据库已落库报告补齐历史任务（跨重启 / 超出内存历史上限）
        try:
            reports = store.list_reports(limit=max(limit * 2, 50))["items"]
        except Exception as e:  # noqa: BLE001 —— 数据库异常不影响内存任务返回
            logger.debug(f"从数据库恢复任务列表失败: {e}")
            reports = []
        for r in reports:
            tid = r.get("task_id")
            if tid and tid not in result:
                result[tid] = self._task_from_report(r)
        ordered = sorted(result.values(), key=lambda d: d.get("created_ts") or 0, reverse=True)
        return ordered[:limit]

    @staticmethod
    def _task_from_report(r: Dict[str, Any]) -> Dict[str, Any]:
        """将数据库中的一条报告记录还原为任务展示对象，供任务中心离线恢复。"""
        status = r.get("status") or STATUS_SUCCESS
        if status == STATUS_SUCCESS:
            message = f"分析完成，共归纳 {r.get('news_count') or 0} 条资讯"
        else:
            message = r.get("error") or "分析失败"
        return {
            "task_id": r.get("task_id") or f"report-{r.get('id')}",
            "status": status,
            "stage": "done",
            "stage_label": "已完成",
            "progress": 100.0,
            "message": message,
            "hours": r.get("window_hours") or 24,
            "scope": r.get("scope") or collector.SCOPE_ALL,
            "report_type": r.get("report_type") or "review",
            "stock_code": r.get("stock_code") or "",
            "provider_name": r.get("provider_name") or "",
            "model": r.get("model") or "",
            "news_count": r.get("news_count") or 0,
            "scanned_count": r.get("scanned_count") or 0,
            "report_id": r.get("id"),
            "error": r.get("error") or "",
            "error_kind": "",
            "created_ts": r.get("created_ts") or 0,
            "started_ts": r.get("start_ts") or 0,
            "finished_ts": r.get("end_ts") or 0,
            "elapsed": r.get("elapsed") or 0,
            "options": {},
        }

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
            if t.status == STATUS_PENDING and task_id in self._queue:
                # 排队中的任务尚未启动，直接出队置为取消
                self._queue.remove(task_id)
                t.status = STATUS_CANCELLED
                t.stage = "done"
                t.progress = 100
                t.message = "任务已取消（尚未开始）"
                t.finished_ts = time.time()
                return True
            self._cancel_flags[task_id] = True
            t.message = "正在取消…"
        return True

    def retry(self, task_id: str) -> Dict[str, Any]:
        """重试失败/已取消的任务：复用原提交参数重新入队。"""
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return {"ok": False, "error": "任务不存在或已过期"}
            if t.status in (STATUS_PENDING, STATUS_RUNNING):
                return {"ok": False, "error": "任务仍在运行中"}
            options = dict(t.options or {})
            provider_name = t.provider_name
        # 释放锁后再提交（submit 自身会加锁）
        if provider_name and not options.get("provider_id"):
            with self._lock:
                for p in cfg.list_providers():
                    if p.name == provider_name:
                        options["provider_id"] = p.id
                        break
        result = self.submit(options)
        if result.get("ok"):
            result["retried_from"] = task_id
        return result

    def submit(self, options: Dict[str, Any]) -> Dict[str, Any]:
        """提交分析任务。运行中有任务时自动排队（上限 MAX_QUEUE_SIZE）。

        返回 {ok, task_id, error, queued}
        """
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
        report_type = options.get("report_type") or "review"
        if report_type not in analyzer_prompts.REPORT_TYPES:
            report_type = "review"
        stock_code = str(options.get("stock_code") or "").strip()
        if report_type == "stock" and not stock_code:
            return {"ok": False, "error": "个股深度报告需要提供股票代码（stock_code）"}

        queued = False
        with self._lock:
            busy = bool(
                self._active_id
                and self._tasks.get(self._active_id)
                and self._tasks[self._active_id].status in (STATUS_PENDING, STATUS_RUNNING)
            )
            if busy and len(self._queue) >= MAX_QUEUE_SIZE:
                return {
                    "ok": False,
                    "error": f"任务繁忙且排队已满（{MAX_QUEUE_SIZE} 个），请稍后再试",
                    "active": self._tasks[self._active_id].to_dict() if self._active_id in self._tasks else None,
                }
            queued = busy

            state = TaskState(
                task_id=task_id,
                status=STATUS_PENDING,
                hours=hours,
                scope=scope,
                report_type=report_type,
                stock_code=stock_code,
                provider_name=provider.name,
                model=provider.model,
                options=dict(options),
                message="排队中，等待空闲…" if queued else "任务已创建",
            )
            self._tasks[task_id] = state
            self._order.append(task_id)
            self._cancel_flags[task_id] = False
            if queued:
                self._queue.append(task_id)
            else:
                self._active_id = task_id
            while len(self._order) > MAX_TASK_HISTORY:
                old = self._order.pop(0)
                self._tasks.pop(old, None)
                self._cancel_flags.pop(old, None)
                if old in self._queue:
                    self._queue.remove(old)

        if not queued:
            self._spawn(task_id, provider, options)
        logger.info(
            f"LLM 分析任务已提交: {task_id} 类型={report_type}"
            f"{' 标的=' + stock_code if stock_code else ''} "
            f"窗口={hours}h 范围={scope} 模型={provider.model}"
            f"{'（排队中）' if queued else ''}"
        )
        return {"ok": True, "task_id": task_id, "task": state.to_dict(), "queued": queued}

    def _spawn(self, task_id: str, provider, options: Dict[str, Any]) -> None:
        thread = threading.Thread(
            target=self._run,
            args=(task_id, provider, options),
            daemon=True,
            name=f"llm-analysis-{task_id}",
        )
        thread.start()

    def _start_next(self) -> None:
        """当前任务结束后从队列取下一个排队任务启动。"""
        with self._lock:
            next_id = None
            while self._queue:
                cand = self._queue.pop(0)
                t = self._tasks.get(cand)
                if t and t.status == STATUS_PENDING:
                    next_id = cand
                    break
            if not next_id:
                self._active_id = None
                return
            self._active_id = next_id
            provider = None
            options: Dict[str, Any] = {}
            if next_id in self._tasks:
                provider_name = self._tasks[next_id].provider_name
                options = dict(self._tasks[next_id].options or {})
            else:
                provider_name = ""
        # 释放锁后再解析 provider 并启动线程
        if provider_name and not options.get("provider_id"):
            for p in cfg.list_providers():
                if p.name == provider_name:
                    options["provider_id"] = p.id
                    break
        provider = None
        pid = options.get("provider_id")
        if pid:
            try:
                provider = cfg.get_provider(int(pid))
            except (TypeError, ValueError):
                provider = None
        if provider is None:
            provider = cfg.get_default_provider()
        if provider is None:
            self._update(next_id, status=STATUS_FAILED, stage="done", progress=100,
                         message="模型配置缺失", error="模型配置缺失", finished_ts=time.time())
            with self._lock:
                if self._active_id == next_id:
                    self._active_id = None
            self._start_next()
            return
        self._publish(next_id, event="status", status=STATUS_RUNNING)
        self._spawn(next_id, provider, options)

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
        self._update(
            task_id,
            status=STATUS_RUNNING,
            started_ts=time.time(),
            stage="collect",
            progress=1,
            message="任务启动中…",
        )

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
                self._publish(
                    task_id,
                    event="stage",
                    stage=stage,
                    stage_label=STAGE_LABELS.get(stage, stage),
                    progress=round(pct, 1),
                    message=msg,
                )

            def on_delta(piece: str):
                # "" 为「清空缓冲」信号（流式回退非流式时由 analyzer 发出）
                if piece:
                    self._publish(task_id, event="delta", text=piece)
                else:
                    self._publish(task_id, event="reset")

            self._publish(task_id, event="status", status=STATUS_RUNNING)

            result = analyzer.run_analysis(
                client,
                hours=collector.normalize_window(options.get("hours", 24)),
                scope=options.get("scope") or collector.SCOPE_ALL,
                report_type=str(options.get("report_type") or "review"),
                stock_code=str(options.get("stock_code") or ""),
                min_importance=_num("min_importance", float, 0.0, 0.0, 10.0),
                max_items=_num("max_items", int, 500, 20, 5000),
                order=options.get("order") or collector.ORDER_IMPORTANCE,
                chunk_chars=_num("chunk_chars", int, 8000, 2000, 40000),
                max_chunks=_num("max_chunks", int, 20, 1, 60),
                focus=str(options.get("focus") or ""),
                news_id=options.get("news_id"),
                progress=on_progress,
                should_cancel=lambda: self._should_cancel(task_id),
                on_delta=on_delta,
            )

            report_id = store.save_report(
                {
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
                    "report_type": result.get("report_type", "review"),
                    "stock_code": result.get("stock_code", ""),
                    "sources": result.get("sources", []),
                    "options": dict(options),
                }
            )

            self._update(
                task_id,
                status=STATUS_SUCCESS,
                stage="done",
                progress=100,
                message=f"分析完成，共归纳 {result['news_count']} 条资讯",
                news_count=result["news_count"],
                scanned_count=result["scanned_count"],
                chunk_count=result["chunk_count"],
                report_id=report_id,
                finished_ts=time.time(),
            )
            self._publish(
                task_id,
                event="done",
                status=STATUS_SUCCESS,
                report_id=report_id,
                news_count=result["news_count"],
            )
            logger.info(f"LLM 分析任务完成: {task_id} report_id={report_id}")

        except AnalysisCancelled:
            self._update(
                task_id,
                status=STATUS_CANCELLED,
                stage="done",
                progress=100,
                message="任务已取消",
                finished_ts=time.time(),
            )
            self._publish(task_id, event="done", status=STATUS_CANCELLED)
            logger.info(f"LLM 分析任务被取消: {task_id}")
        except LLMError as e:
            self._update(
                task_id,
                status=STATUS_FAILED,
                stage="done",
                progress=100,
                message=e.message,
                error=e.message,
                error_kind=e.kind,
                finished_ts=time.time(),
            )
            self._persist_failure(task_id, provider.name, options, e.message)
            self._publish(
                task_id, event="done", status=STATUS_FAILED, error=e.message, error_kind=e.kind
            )
            logger.warning(f"LLM 分析任务失败: {task_id} - {e.message}")
        except Exception as e:
            msg = f"{type(e).__name__}: {str(e)[:200]}"
            self._update(
                task_id,
                status=STATUS_FAILED,
                stage="done",
                progress=100,
                message=msg,
                error=msg,
                error_kind="unknown",
                finished_ts=time.time(),
            )
            self._persist_failure(task_id, provider.name, options, msg)
            self._publish(
                task_id, event="done", status=STATUS_FAILED, error=msg, error_kind="unknown"
            )
            logger.error(f"LLM 分析任务异常: {task_id} - {msg}", exc_info=True)
        finally:
            with self._lock:
                if self._active_id == task_id:
                    self._active_id = None
            self._start_next()

    def _persist_failure(
        self, task_id: str, provider_name: str, options: Dict[str, Any], error: str
    ) -> None:
        """失败任务落库：报告页可见失败记录并可重试（options 供跨重启重试）。"""
        try:
            report_type = str(options.get("report_type") or "review")
            label = analyzer_prompts.REPORT_TYPES.get(report_type, {}).get("label", "复盘简报")
            stock_code = str(options.get("stock_code") or "")
            store.save_report(
                {
                    "task_id": task_id,
                    "title": f"分析失败 · {label}" + (f" · {stock_code}" if stock_code else ""),
                    "provider_name": provider_name,
                    "model": "",
                    "window_hours": collector.normalize_window(options.get("hours", 24)),
                    "scope": options.get("scope") or collector.SCOPE_ALL,
                    "status": "failed",
                    "content": "",
                    "stats": {},
                    "error": error,
                    "report_type": report_type,
                    "stock_code": stock_code,
                    "sources": [],
                    "options": dict(options),
                }
            )
        except Exception as e:  # noqa: BLE001 —— 失败落库失败不影响任务状态
            logger.debug(f"失败报告落库异常: {e}")


_service: Optional[AnalysisService] = None
_service_lock = threading.Lock()


def get_service() -> AnalysisService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = AnalysisService()
    return _service
