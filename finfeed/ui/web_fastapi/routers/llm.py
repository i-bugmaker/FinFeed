"""AI 分析 HTTP 传输层（FastAPI 原生路由）。

分层约定（见 docs/ARCHITECTURE.md）：
  - 本模块只做「校验输入 -> 调用服务 -> 映射响应」；
    用例编排位于 finfeed.application.llm_service，领域逻辑在 finfeed.llm。
  - 预期失败抛 :class:`ApiError`，由应用边界统一序列化为
    ``{ success: false, error: { code, message, details } }``；
    任务提交/重试的「操作结果载荷」（ok/error 字段）保持旧形状以兼容前端。
  - 公开 URL 与成功响应形状与旧 handle_get/handle_post 完全一致。

SSE 流式：
  - ``GET /api/llm/task/stream?id=<task_id>`` 推送 stage/delta/done 事件；
  - 领域层 AnalysisService 通过注入的 publisher 回调发布事件，
    本模块维护按 task_id 分组的订阅队列（仅订阅该任务的连接收到增量）。
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from finfeed.application import llm_service
from finfeed.llm import collector, store
from finfeed.llm import config as cfg
from finfeed.llm import prompts as llm_prompts
from finfeed.llm import sessions as _sessions
from finfeed.llm.client import build_client
from finfeed.llm.schema import ensure_tables
from finfeed.llm.service import get_service
from finfeed.ui.web_fastapi.core.errors import ApiError

logger = logging.getLogger("news_monitor")

# ============================================================
# 任务事件订阅注册表（SSE）
# ============================================================
_STREAM_QUEUE_SIZE = 256
_STREAM_IDLE_TIMEOUT = 15.0  # 无事件时的心跳间隔（秒）
_STREAM_MAX_LIFETIME = 2100.0  # 单连接最长寿命（秒），兜底防泄漏

_stream_lock = threading.Lock()
_stream_queues: Dict[str, Set[queue.Queue]] = {}


def publish_llm_task_event(task_id: str, payload: Dict[str, Any]) -> None:
    """向订阅了指定任务的 SSE 连接发布事件。

    由 app.py 注入到 AnalysisService；慢客户端直接丢弃增量（进度可由
    轮询恢复，delta 属可再生数据，不值得为它阻塞分析线程）。
    """
    with _stream_lock:
        queues = list(_stream_queues.get(task_id, ()))
    for q in queues:
        try:
            q.put_nowait(payload)
        except queue.Full:
            try:
                q.put_nowait({"event": "reset"})
            except queue.Full:
                pass


def _subscribe(task_id: str) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=_STREAM_QUEUE_SIZE)
    with _stream_lock:
        _stream_queues.setdefault(task_id, set()).add(q)
    return q


def _unsubscribe(task_id: str, q: queue.Queue) -> None:
    with _stream_lock:
        clients = _stream_queues.get(task_id)
        if clients is not None:
            clients.discard(q)
            if not clients:
                _stream_queues.pop(task_id, None)


# ============================================================
# 请求模型（extra=allow：容忍前端携带的多余字段）
# ============================================================
class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class AnalyzeRequest(_Loose):
    provider_id: Optional[int] = None
    hours: int = Field(default=24, ge=1, le=168)
    scope: str = "all"
    report_type: str = "review"
    stock_code: str = ""
    focus: str = ""
    min_importance: float = Field(default=0.0, ge=0.0, le=10.0)
    max_items: int = Field(default=500, ge=20, le=5000)
    order: str = "importance"
    chunk_chars: int = Field(default=8000, ge=2000, le=40000)
    max_chunks: int = Field(default=20, ge=1, le=60)


class ProviderSaveRequest(_Loose):
    name: str = ""
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout: int = 120
    extra_headers: Optional[Any] = None
    preset: str = "custom"
    enabled: bool = True
    is_default: bool = False
    id: Optional[int] = None


class ProviderTestRequest(_Loose):
    id: Optional[int] = None
    use_saved: bool = False


class IdRequest(_Loose):
    id: int = 0


class SessionCreateRequest(_Loose):
    title: str = "新会话"


class SessionRenameRequest(_Loose):
    id: int = 0
    title: str = ""


class SessionMessageRequest(_Loose):
    id: int = 0
    role: str = "user"
    content: str = ""


class TaskIdRequest(_Loose):
    task_id: str = ""


class ReportPinRequest(_Loose):
    id: int = 0
    pinned: bool = True


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str = "user"
    content: str = ""


class ChatRequest(_Loose):
    report_id: int = 0
    question: str = ""
    message: str = ""
    stock_code: str = ""
    stock_name: str = ""
    history: Optional[list[ChatTurn]] = None


class AnalysisConfigRequest(_Loose):
    scope: Optional[str] = None
    window: Optional[int] = None
    focus: Optional[str] = None
    report_type: Optional[str] = None


class PromptsSaveRequest(_Loose):
    """自定义提示词：键 prompt_<name> 或直接 <name>。"""

    def collect(self) -> Dict[str, str]:
        values: Dict[str, str] = {}
        for key, value in self.model_dump(exclude_unset=True).items():
            name = key[7:] if key.startswith("prompt_") else key
            values[name] = value
        return values


# ============================================================
# 工具
# ============================================================
def _respond(data: Dict[str, Any], status: int = 200):
    """200 返回 dict（FastAPI 自动序列化）；非 200 显式携带状态码。"""
    if status == 200:
        return data
    return JSONResponse(content=data, status_code=status)


def _require(
    condition: Any, message: str, *, status_code: int = 404, code: str = "NOT_FOUND"
) -> Any:
    if not condition:
        raise ApiError(message, status_code=status_code, code=code)
    return condition


def create_router() -> APIRouter:
    router = APIRouter(tags=["llm"])

    # --------------------------------------------------
    # 报告导出（二进制响应）
    # --------------------------------------------------
    @router.get("/api/llm/report/export")
    def export_report(id: int = Query(0), fmt: str = Query("md")) -> Response:
        result = llm_service.export_report(id, fmt)
        _require(result, "报告不存在")
        filename, body, content_type = result
        return Response(
            content=body,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # --------------------------------------------------
    # GET 查询类
    # --------------------------------------------------
    @router.get("/api/llm/status")
    def status() -> Dict[str, Any]:
        ensure_tables()
        return _respond(llm_service.status_payload())

    @router.get("/api/llm/init")
    def init() -> Dict[str, Any]:
        ensure_tables()
        return _respond(llm_service.init_payload())

    @router.get("/api/llm/presets")
    def presets() -> Dict[str, Any]:
        return _respond(
            {
                "presets": cfg.PRESETS,
                "scopes": [{"key": k, "label": v} for k, v in collector.SCOPES.items()],
                "windows": list(collector.ALLOWED_WINDOWS),
                "report_types": [
                    {"key": k, **v} for k, v in llm_prompts.REPORT_TYPES.items()
                ],
            }
        )

    @router.get("/api/llm/config")
    def get_analysis_config() -> Dict[str, Any]:
        return _respond({"defaults": llm_service.analysis_defaults()})

    @router.post("/api/llm/config")
    def save_analysis_config(req: AnalysisConfigRequest) -> Dict[str, Any]:
        payload = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
        defaults = llm_service.save_analysis_defaults(payload)
        return _respond({"success": True, "defaults": defaults})

    @router.get("/api/llm/prompts")
    def get_prompts() -> Dict[str, Any]:
        return _respond(llm_service.prompts_payload())

    @router.get("/api/llm/providers")
    def providers() -> Dict[str, Any]:
        items = [p.to_dict() for p in cfg.list_providers()]
        return _respond({"providers": items, "count": len(items)})

    @router.get("/api/llm/provider")
    def provider_detail(id: int = Query(0)) -> Dict[str, Any]:
        p = cfg.get_provider(id)
        _require(p, "配置不存在")
        return _respond({"provider": p.to_dict()})

    @router.get("/api/llm/preview")
    def preview(
        hours: int = Query(24, ge=1, le=168),
        scope: str = Query(collector.SCOPE_ALL),
        min_importance: float = Query(0.0, ge=0.0, le=10.0),
        max_items: int = Query(500, ge=20, le=5000),
    ) -> Dict[str, Any]:
        data = collector.preview_window(hours=hours, scope=scope, min_importance=min_importance)
        data["estimate"] = llm_service.preview_estimate(data["matched"], max_items)
        return _respond(data)

    @router.get("/api/llm/task")
    def task(id: str = Query("")) -> Dict[str, Any]:
        svc = get_service()
        t = svc.get_task(id) if id else svc.get_active()
        if not t:
            return _respond({"task": None})
        payload: Dict[str, Any] = {"task": t}
        if t.get("status") == "success" and t.get("report_id"):
            payload["report"] = store.get_report(t["report_id"])
        return _respond(payload)

    @router.get("/api/llm/tasks")
    def tasks(limit: int = Query(10, ge=1, le=100)) -> Dict[str, Any]:
        return _respond({"tasks": get_service().list_tasks(limit=limit)})

    @router.get("/api/llm/task/retry")
    def task_retry_get(id: str = Query("")) -> Dict[str, Any]:
        return _retry_result(get_service().retry(id))

    @router.get("/api/llm/sessions")
    def sessions(limit: int = Query(100, ge=1, le=200)) -> Dict[str, Any]:
        ensure_tables()
        return _respond({"sessions": _sessions.list_sessions(limit=limit)})

    @router.get("/api/llm/sessions/messages")
    def session_messages(id: int = Query(0)) -> Dict[str, Any]:
        ensure_tables()
        return _respond({"messages": _sessions.list_messages(id) if id else []})

    @router.get("/api/llm/reports")
    def reports(
        q: str = Query(""),
        limit: int = Query(30, ge=1, le=200),
        offset: int = Query(0, ge=0),
        pinned: str = Query("0"),
    ) -> Dict[str, Any]:
        keyword = q.strip()
        if keyword:
            return _respond(store.search_reports(keyword, limit=limit))
        return _respond(
            store.list_reports(
                limit=limit,
                offset=offset,
                pinned_only=pinned == "1",
            )
        )

    @router.get("/api/llm/report")
    def report_detail(id: int = Query(0)) -> Dict[str, Any]:
        rep = store.get_report(id)
        _require(rep, "报告不存在")
        return _respond({"report": rep})

    # --------------------------------------------------
    # SSE：任务事件流（stage / delta / reset / done）
    # --------------------------------------------------
    @router.get("/api/llm/task/stream")
    def task_stream(id: str = Query(..., min_length=4)) -> StreamingResponse:
        svc = get_service()
        task_state = svc.get_task(id)
        if not task_state:
            raise ApiError("任务不存在或已过期", status_code=404, code="NOT_FOUND")

        q = _subscribe(id)

        # 迟到订阅：任务已终结则立即补发终态后关闭
        if task_state.get("status") in ("success", "failed", "cancelled"):
            q.put(
                {
                    "event": "done",
                    "status": task_state["status"],
                    "report_id": task_state.get("report_id") or 0,
                    "error": task_state.get("error") or "",
                }
            )

        stopped = threading.Event()

        async def stream():
            import asyncio

            events: "asyncio.Queue[tuple[str, Any]]" = asyncio.Queue()
            running_loop = asyncio.get_running_loop()
            thread = threading.Thread(
                target=_pump_stream,
                args=(q, events, running_loop, stopped),
                daemon=True,
                name=f"llm-stream-{id}",
            )
            thread.start()
            try:
                yield 'event: connected\ndata: {"type":"connected"}\n\n'
                waited = 0.0
                while waited < _STREAM_MAX_LIFETIME:
                    try:
                        kind, item = await asyncio.wait_for(events.get(), timeout=5.0)
                    except asyncio.TimeoutError:
                        waited += 5.0
                        yield ": keep-alive\n\n"
                        continue
                    if kind == "ping":
                        yield ": ping\n\n"
                    else:
                        event_name = str(item.get("event") or "message")
                        if event_name != "status":  # 起始状态不推送，前端靠轮询兜底
                            yield (
                                f"event: {event_name}\n"
                                f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                            )
                            if event_name == "done":
                                break
                    waited += _STREAM_IDLE_TIMEOUT
            finally:
                stopped.set()
                _unsubscribe(id, q)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # --------------------------------------------------
    # POST 操作类
    # --------------------------------------------------
    @router.post("/api/llm/provider/save")
    def provider_save(req: ProviderSaveRequest) -> Dict[str, Any]:
        ensure_tables()
        try:
            p = cfg.save_provider(req.model_dump(exclude_none=True))
        except ValueError as ve:
            raise ApiError(str(ve), status_code=400, code="VALIDATION") from ve
        return _respond({"success": True, "provider": p.to_dict()})

    @router.post("/api/llm/provider/delete")
    def provider_delete(req: IdRequest) -> Dict[str, Any]:
        ensure_tables()
        ok = cfg.delete_provider(req.id)
        if not ok:
            raise ApiError("配置不存在", status_code=404, code="NOT_FOUND")
        return _respond({"success": True})

    @router.post("/api/llm/provider/default")
    def provider_default(req: IdRequest) -> Dict[str, Any]:
        ensure_tables()
        ok = cfg.set_default_provider(req.id)
        if not ok:
            raise ApiError("配置不存在", status_code=404, code="NOT_FOUND")
        return _respond({"success": True})

    @router.post("/api/llm/provider/test")
    def provider_test(req: ProviderTestRequest) -> Dict[str, Any]:
        ensure_tables()
        if req.use_saved and req.id:
            provider = cfg.get_provider(req.id)
            _require(provider, "配置不存在")
        else:
            provider = cfg.provider_from_payload(req.model_dump(exclude_none=True))
        if not provider.base_url:
            raise ApiError("接口地址不能为空", status_code=400, code="VALIDATION")

        client = build_client(provider)
        result = client.test_connection()
        return _respond(llm_service.provider_test_result(provider, result))

    @router.post("/api/llm/prompts")
    def prompts_save(req: PromptsSaveRequest) -> Dict[str, Any]:
        saved = llm_service.save_prompts(req.collect())
        return _respond({"success": True, "saved": saved})

    @router.post("/api/llm/analyze")
    def analyze(req: AnalyzeRequest) -> Dict[str, Any]:
        ensure_tables()
        result = get_service().submit(req.model_dump())
        # 保持旧「操作结果」形状：200 {ok:true,...} / 409 {ok:false, error, active}
        return _respond(result, status=200 if result.get("ok") else 409)

    @router.post("/api/llm/task/cancel")
    def task_cancel(req: TaskIdRequest) -> Dict[str, Any]:
        ok = get_service().cancel(req.task_id)
        if not ok:
            raise ApiError("任务不存在或已结束", status_code=404, code="NOT_FOUND")
        return _respond({"success": True})

    @router.post("/api/llm/task/retry")
    def task_retry_post(req: TaskIdRequest) -> Dict[str, Any]:
        return _retry_result(get_service().retry(req.task_id))

    @router.post("/api/llm/sessions")
    def session_create(req: SessionCreateRequest) -> Dict[str, Any]:
        ensure_tables()
        session = _sessions.create_session(req.title or "新会话")
        return _respond({"success": True, "session": session})

    @router.post("/api/llm/sessions/rename")
    def session_rename(req: SessionRenameRequest) -> Dict[str, Any]:
        ensure_tables()
        ok = _sessions.rename_session(req.id, req.title)
        if not ok:
            raise ApiError("会话不存在", status_code=404, code="NOT_FOUND")
        return _respond({"success": True})

    @router.post("/api/llm/sessions/delete")
    def session_delete(req: IdRequest) -> Dict[str, Any]:
        ensure_tables()
        ok = _sessions.delete_session(req.id)
        if not ok:
            raise ApiError("会话不存在", status_code=404, code="NOT_FOUND")
        return _respond({"success": True})

    @router.post("/api/llm/sessions/messages")
    def session_add_message(req: SessionMessageRequest) -> Dict[str, Any]:
        ensure_tables()
        msg = _sessions.add_message(req.id, req.role, req.content)
        if msg is None:
            raise ApiError("消息内容不能为空", status_code=400, code="VALIDATION")
        return _respond({"success": True, "message": msg})

    @router.post("/api/llm/report/delete")
    def report_delete(req: IdRequest) -> Dict[str, Any]:
        ensure_tables()
        ok = store.delete_report(req.id)
        if not ok:
            raise ApiError("报告不存在", status_code=404, code="NOT_FOUND")
        return _respond({"success": True})

    @router.post("/api/llm/report/retry")
    def report_retry(req: IdRequest) -> Dict[str, Any]:
        """按报告归档的提交参数重新发起分析（支持跨重启重试失败任务）。"""
        rep = store.get_report(req.id)
        _require(rep, "报告不存在")
        options = dict(rep.get("options") or {})
        if not options:
            raise ApiError("该报告没有归档提交参数，无法重试", status_code=400, code="VALIDATION")
        result = get_service().submit(options)
        return _respond(result, status=200 if result.get("ok") else 409)

    @router.post("/api/llm/report/pin")
    def report_pin(req: ReportPinRequest) -> Dict[str, Any]:
        ensure_tables()
        ok = store.set_pinned(req.id, req.pinned)
        if not ok:
            raise ApiError("报告不存在", status_code=404, code="NOT_FOUND")
        return _respond({"success": True, "pinned": req.pinned})

    @router.post("/api/llm/reports/clear")
    def reports_clear() -> Dict[str, Any]:
        n = store.clear_reports()
        return _respond({"success": True, "deleted": n})

    @router.post("/api/llm/chat")
    def chat(req: ChatRequest) -> Dict[str, Any]:
        ensure_tables()
        question = (req.question or req.message or "").strip()
        if not question:
            raise ApiError("请输入问题", status_code=400, code="VALIDATION")
        history = [t.model_dump() for t in req.history] if req.history else None

        try:
            payload = llm_service.dispatch_chat(
                question,
                req.report_id,
                history,
                stock_code=req.stock_code or "",
                stock_name=req.stock_name or "",
            )
        except Exception:
            logger.exception("LLM 对话异常")
            raise ApiError(
                "服务暂时不可用，请稍后重试", status_code=500, code="INTERNAL_ERROR"
            ) from None

        if payload.get("ok"):
            return _respond(payload)

        # 业务失败映射：报告不存在 404 / 模型未配置或禁用 409 / 上游错误 502
        kind = payload.get("kind")
        if kind == "not_found":
            raise ApiError(payload.get("error") or "报告不存在", status_code=404, code="NOT_FOUND")
        raise ApiError(
            payload.get("error") or "对话失败",
            status_code=502
            if kind in ("auth", "ratelimit", "server", "network", "timeout", "protocol", "endpoint")
            else 409,
            code="UPSTREAM" if kind else "CONFLICT",
            details={"kind": kind} if kind else None,
        )

    def _retry_result(result: Dict[str, Any]) -> Dict[str, Any]:
        """保持旧形状：200 {ok:true,...} / 409 {ok:false, error}"""
        return _respond(result, status=200 if result.get("ok") else 409)

    return router


def _pump_stream(
    q: "queue.Queue[Dict[str, Any]]",
    events: Any,
    running_loop: Any,
    stopped: threading.Event,
) -> None:
    """后台线程：阻塞队列 -> asyncio 队列桥接（复用 realtime.py 的成熟模式）。"""
    import asyncio

    while not stopped.is_set():
        try:
            item = q.get(timeout=_STREAM_IDLE_TIMEOUT)
        except queue.Empty:
            asyncio.run_coroutine_threadsafe(events.put(("ping", None)), running_loop)
            continue
        asyncio.run_coroutine_threadsafe(events.put(("data", item)), running_loop)
        if item.get("event") == "done":
            return
