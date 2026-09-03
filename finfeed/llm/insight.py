#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轻量洞察任务引擎（非新闻口径）

与 :mod:`finfeed.llm.service` 的分工：

  - ``AnalysisService`` 面向「检索新闻库 -> 分批压缩 -> 汇总成文」的重型报告，
    产出落报告库、可导出、可追问；
  - 本模块面向「已结构化的盘面数据 -> 一次对话 -> 流式输出」的轻量洞察，
    不检索新闻，只做任务状态跟踪、增量发布与结果缓存；运行期可通过
    ``set_persister`` 注册钩子，把成功结果归档到报告库以便历史回看。

事件协议与 ``AnalysisService`` 完全一致（``stage`` / ``delta`` / ``reset`` /
``done``），因此可复用 llm 路由中的 SSE 订阅注册表与桥接函数。

并发策略：同一时刻允许多个洞察任务并行（不同模块各管各的），但同一
``cache_key`` 只保留一份最近结果，重复点击直接命中缓存，避免重复计费。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config as cfg
from .client import LLMError, build_client

logger = logging.getLogger("news_monitor")

MAX_TASK_HISTORY = 20
MAX_CACHE_ENTRIES = 8

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# 非流式回退时把整段结果切成小块推送，避免单帧过大
_FALLBACK_CHUNK = 400

# 允许「流式 -> 非流式」回退的错误类型（见 _call）
_FALLBACK_KINDS = frozenset(
    {"stream_broken", "protocol", "timeout", "network", "server", "ratelimit", "unknown"}
)

STAGE_LABELS = {
    "queued": "排队中",
    "prepare": "准备数据",
    "think": "模型分析中",
    "stream": "生成结果",
    "done": "已完成",
}


class InsightCancelled(Exception):
    """洞察任务被用户取消"""


@dataclass
class InsightTask:
    """洞察任务状态"""

    task_id: str
    kind: str = "insight"
    title: str = ""
    status: str = STATUS_PENDING
    stage: str = "queued"
    stage_label: str = "排队中"
    progress: float = 0.0
    message: str = "任务已创建"
    provider_name: str = ""
    model: str = ""
    content: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed: float = 0.0
    cached: bool = False
    error: str = ""
    error_kind: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    created_ts: float = field(default_factory=time.time)
    started_ts: float = 0.0
    finished_ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["elapsed"] = round(
            (self.finished_ts or time.time()) - (self.started_ts or self.created_ts), 1
        )
        return d


class InsightService:
    """洞察任务管理器（单例）"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tasks: Dict[str, InsightTask] = {}
        self._order: List[str] = []
        self._cancel_flags: Dict[str, bool] = {}
        # 结果缓存：cache_key -> {content, provider_name, model, meta, tokens}
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_order: List[str] = []
        # 事件发布器：fn(task_id, payload)，由传输层（SSE）注入
        self._publisher: Optional[Callable[[str, Dict[str, Any]], None]] = None
        # 结果持久化钩子：fn(task_dict)，由应用层注入（归档到 llm_reports 以便历史回看）
        self._persister: Optional[Callable[[Dict[str, Any]], None]] = None

    # ---------- 事件发布 ----------
    def set_event_publisher(self, fn: Optional[Callable[[str, Dict[str, Any]], None]]) -> None:
        with self._lock:
            self._publisher = fn

    def set_persister(self, fn: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        with self._lock:
            self._persister = fn

    def _publish(self, task_id: str, **payload: Any) -> None:
        with self._lock:
            fn = self._publisher
        if fn is None:
            return
        try:
            fn(task_id, {"task_id": task_id, **payload})
        except Exception as e:  # noqa: BLE001 —— 订阅方异常绝不影响分析主流程
            logger.debug(f"洞察任务事件发布失败: {e}")

    # ---------- 查询 ----------
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            t = self._tasks.get(task_id)
            return t.to_dict() if t else None

    def list_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._lock:
            ids = self._order[-limit:][::-1]
            return [self._tasks[i].to_dict() for i in ids if i in self._tasks]

    # ---------- 缓存 ----------
    def cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._cache.get(key)
            return dict(item) if item else None

    def cache_clear(self, key: Optional[str] = None) -> int:
        """清除缓存；key 为空则清空全部。返回清除条数。"""
        with self._lock:
            if key:
                existed = self._cache.pop(key, None)
                if key in self._cache_order:
                    self._cache_order.remove(key)
                return 1 if existed else 0
            n = len(self._cache)
            self._cache.clear()
            self._cache_order.clear()
            return n

    def _cache_put(self, key: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._cache[key] = dict(payload)
            if key in self._cache_order:
                self._cache_order.remove(key)
            self._cache_order.append(key)
            while len(self._cache_order) > MAX_CACHE_ENTRIES:
                old = self._cache_order.pop(0)
                self._cache.pop(old, None)

    # ---------- 控制 ----------
    def cancel(self, task_id: str) -> bool:
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t.status not in (STATUS_PENDING, STATUS_RUNNING):
                return False
            self._cancel_flags[task_id] = True
            t.message = "正在取消…"
        return True

    # ---------- 提交 ----------
    def submit(
        self,
        *,
        messages: List[Dict[str, str]],
        kind: str = "insight",
        title: str = "",
        provider_id: Optional[int] = None,
        cache_key: Optional[str] = None,
        refresh: bool = False,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """提交一次洞察任务。

        Args:
            messages: 已构建好的对话消息（数据装配在调用方完成，本模块只负责调用）。
            kind: 任务类型标识（如 ``limitup``），供前端与日志区分。
            title: 任务标题（展示用）。
            provider_id: 指定模型配置；为空取系统默认配置。
            cache_key: 结果缓存键；命中且 refresh=False 时直接返回已完成结果。
            refresh: True 表示忽略缓存重新分析。
            meta: 随任务回传的展示元信息（如数据日期、样本量）。

        Returns:
            ``{ok, task_id, task, cached}`` 或 ``{ok: False, error}``。
        """
        provider, err = self._resolve_provider(provider_id)
        if provider is None:
            return {"ok": False, "error": err or "尚未配置任何大语言模型"}

        task_id = uuid.uuid4().hex[:16]
        if cache_key and not refresh:
            hit = self.cache_get(cache_key)
            if hit:
                task = InsightTask(
                    task_id=task_id,
                    kind=kind,
                    title=title,
                    status=STATUS_SUCCESS,
                    stage="done",
                    stage_label="已完成",
                    progress=100,
                    message="已命中本次缓存结果",
                    provider_name=hit.get("provider_name") or provider.name,
                    model=hit.get("model") or provider.model,
                    content=hit.get("content") or "",
                    prompt_tokens=int(hit.get("prompt_tokens") or 0),
                    completion_tokens=int(hit.get("completion_tokens") or 0),
                    cached=True,
                    meta=dict(hit.get("meta") or meta or {}),
                    created_ts=time.time(),
                    started_ts=time.time(),
                    finished_ts=time.time(),
                )
                with self._lock:
                    self._register(task)
                logger.info(f"洞察任务命中缓存: kind={kind} key={cache_key}")
                return {"ok": True, "task_id": task_id, "task": task.to_dict(), "cached": True}

        task = InsightTask(
            task_id=task_id,
            kind=kind,
            title=title,
            provider_name=provider.name,
            model=provider.model,
            meta=dict(meta or {}),
        )
        with self._lock:
            self._register(task)
            self._cancel_flags[task_id] = False

        thread = threading.Thread(
            target=self._run,
            args=(task_id, provider, messages, cache_key),
            daemon=True,
            name=f"llm-insight-{task_id}",
        )
        thread.start()
        logger.info(
            f"洞察任务已提交: {task_id} kind={kind} 模型={provider.model}"
            f"{' 缓存键=' + cache_key if cache_key else ''}"
        )
        return {"ok": True, "task_id": task_id, "task": task.to_dict(), "cached": False}

    def _register(self, task: InsightTask) -> None:
        self._tasks[task.task_id] = task
        self._order.append(task.task_id)
        while len(self._order) > MAX_TASK_HISTORY:
            old = self._order.pop(0)
            self._tasks.pop(old, None)
            self._cancel_flags.pop(old, None)

    @staticmethod
    def _resolve_provider(provider_id: Optional[int]) -> Tuple[Optional[Any], str]:
        provider = None
        if provider_id:
            try:
                provider = cfg.get_provider(int(provider_id))
            except (TypeError, ValueError):
                provider = None
            if provider is None:
                return None, f"模型配置 {provider_id} 不存在"
        if provider is None:
            provider = cfg.get_default_provider()
        if provider is None:
            return None, "尚未配置任何大语言模型，请先在「AI 设置」中添加并测试连通性"
        if not provider.enabled:
            return None, f"配置「{provider.name}」已被禁用"
        return provider, ""

    # ---------- 执行 ----------
    def _update(self, task_id: str, **kwargs: Any) -> None:
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

    def _run(
        self,
        task_id: str,
        provider,
        messages: List[Dict[str, str]],
        cache_key: Optional[str],
    ) -> None:
        self._update(
            task_id,
            status=STATUS_RUNNING,
            started_ts=time.time(),
            stage="think",
            progress=5,
            message="模型分析中…",
        )
        self._publish(task_id, event="status", status=STATUS_RUNNING)
        self._publish(
            task_id, event="stage", stage="think",
            stage_label=STAGE_LABELS["think"], progress=5, message="模型分析中…",
        )

        content = ""
        prompt_tokens = 0
        completion_tokens = 0
        try:
            client = build_client(provider)
            content, prompt_tokens, completion_tokens = self._call(
                task_id, client, messages
            )
        except InsightCancelled:
            self._update(
                task_id, status=STATUS_CANCELLED, stage="done", progress=100,
                message="任务已取消", finished_ts=time.time(),
            )
            self._publish(task_id, event="done", status=STATUS_CANCELLED)
            logger.info(f"洞察任务被取消: {task_id}")
            return
        except LLMError as e:
            self._update(
                task_id, status=STATUS_FAILED, stage="done", progress=100,
                message=e.message, error=e.message, error_kind=e.kind,
                finished_ts=time.time(),
            )
            self._publish(
                task_id, event="done", status=STATUS_FAILED,
                error=e.message, error_kind=e.kind,
            )
            logger.warning(f"洞察任务失败: {task_id} - {e.message}")
            return
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {str(e)[:200]}"
            self._update(
                task_id, status=STATUS_FAILED, stage="done", progress=100,
                message=msg, error=msg, error_kind="unknown",
                finished_ts=time.time(),
            )
            self._publish(
                task_id, event="done", status=STATUS_FAILED,
                error=msg, error_kind="unknown",
            )
            logger.error(f"洞察任务异常: {task_id} - {msg}", exc_info=True)
            return

        content = (content or "").strip()
        if not content:
            error = "模型返回内容为空"
            self._update(
                task_id, status=STATUS_FAILED, stage="done", progress=100,
                message=error, error=error, error_kind="empty",
                finished_ts=time.time(),
            )
            self._publish(
                task_id, event="done", status=STATUS_FAILED,
                error=error, error_kind="empty",
            )
            return

        if cache_key:
            with self._lock:
                meta = dict(self._tasks[task_id].meta) if task_id in self._tasks else {}
            self._cache_put(
                cache_key,
                {
                    "content": content,
                    "provider_name": provider.name,
                    "model": provider.model,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "meta": meta,
                },
            )

        self._update(
            task_id, status=STATUS_SUCCESS, stage="done", progress=100,
            message="分析完成", content=content,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            finished_ts=time.time(),
        )
        self._publish(task_id, event="done", status=STATUS_SUCCESS)
        logger.info(f"洞察任务完成: {task_id} 输出 {len(content)} 字")
        self._persist(task_id)

    def _persist(self, task_id: str) -> None:
        """成功后回调持久化钩子（归档结果，供历史回看；失败不影响主流程）。"""
        with self._lock:
            fn = self._persister
            task = self._tasks.get(task_id)
        if fn is None or task is None:
            return
        try:
            fn(task.to_dict())
        except Exception as e:  # noqa: BLE001 —— 归档异常仅记日志，不回滚已成功的分析
            logger.warning(f"洞察任务持久化失败: {task_id} - {e}")

    def _call(
        self, task_id: str, client, messages: List[Dict[str, str]]
    ) -> Tuple[str, int, int]:
        """流式调用；不支持或中断时回退非流式全量取回。"""
        pieces: List[str] = []
        prompt_tokens = 0
        completion_tokens = 0
        started = False
        try:
            for ev in client.chat_stream(messages):
                if self._should_cancel(task_id):
                    raise InsightCancelled()
                kind = ev.get("type")
                if kind == "usage":
                    prompt_tokens = int(ev.get("prompt_tokens") or 0)
                    completion_tokens = int(ev.get("completion_tokens") or 0)
                    continue
                if kind != "delta":
                    continue
                text = ev.get("text") or ""
                if not text:
                    continue
                if not started:
                    started = True
                    self._update(
                        task_id, stage="stream", progress=45, message="正在生成分析结论…"
                    )
                    self._publish(
                        task_id, event="stage", stage="stream",
                        stage_label=STAGE_LABELS["stream"], progress=45,
                        message="正在生成分析结论…",
                    )
                pieces.append(text)
                self._publish(task_id, event="delta", text=text)
            return "".join(pieces), prompt_tokens, completion_tokens
        except LLMError as e:
            # 仅对「流式特有 / 可重试」的失败回退非流式：
            #   · 已吐出增量后中断（stream_broken）→ 增量不可信，整段重取；
            #   · 首字节前失败但属传输/协议/服务端类 → 可能是上游不支持 stream；
            #   · 鉴权/参数/端点类失败 → 非流式必然同样失败，直接上抛避免双倍等待。
            if not pieces and e.kind not in _FALLBACK_KINDS:
                raise
            logger.info(f"洞察流式输出不可用（{e.kind}），回退非流式: {e.message}")
            if pieces:
                self._publish(task_id, event="reset")
            result = client.chat(messages)
            content = result.content or ""
            for i in range(0, len(content), _FALLBACK_CHUNK):
                if self._should_cancel(task_id):
                    raise InsightCancelled()
                self._publish(
                    task_id, event="delta", text=content[i : i + _FALLBACK_CHUNK]
                )
            return content, result.prompt_tokens, result.completion_tokens


_service: Optional[InsightService] = None
_service_lock = threading.Lock()


def get_service() -> InsightService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = InsightService()
    return _service
