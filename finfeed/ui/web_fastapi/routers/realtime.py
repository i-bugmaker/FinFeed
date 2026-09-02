"""SSE and WebSocket transport adapters.

The legacy broadcaster is isolated behind a publisher protocol so the next
event-bus implementation can be substituted without changing HTTP handlers.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections.abc import Callable
from typing import Any, Protocol

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import StreamingResponse

from finfeed.ui.web_fastapi.shared import (
    SSE_CLIENT_QUEUE_MAXSIZE,
    _broadcast_watermarks,
    _last_broadcast_ts,
    _sse_clients,
    _sse_clients_lock,
    _watermark_initialized,
    broadcast_new_news,
    get_sse_tick_mtime,
    init_broadcast_watermark,
    touch_sse_tick,
)

SSE_TICK_POLL_INTERVAL = 0.5
SSE_SAFETY_POLL_INTERVAL = 15.0


class NewsEventPublisher(Protocol):
    """Minimal contract required by the realtime HTTP adapter."""

    def add_client(self, client: queue.Queue[dict[str, Any]]) -> None: ...
    def remove_client(self, client: queue.Queue[dict[str, Any]]) -> None: ...
    def initialize(self) -> None: ...
    def touch(self) -> None: ...
    def tick_mtime(self) -> float: ...
    def publish_pending(self) -> None: ...
    def health(self) -> dict[str, Any]: ...


class LegacyNewsEventPublisher:
    """Compatibility adapter around the old process-local broadcaster."""

    queue_size = SSE_CLIENT_QUEUE_MAXSIZE

    def add_client(self, client: queue.Queue[dict[str, Any]]) -> None:
        with _sse_clients_lock:
            _sse_clients.add(client)

    def remove_client(self, client: queue.Queue[dict[str, Any]]) -> None:
        with _sse_clients_lock:
            _sse_clients.discard(client)

    def initialize(self) -> None:
        init_broadcast_watermark()

    def touch(self) -> None:
        touch_sse_tick()

    def tick_mtime(self) -> float:
        return get_sse_tick_mtime()

    def publish_pending(self) -> None:
        broadcast_new_news()

    def health(self) -> dict[str, Any]:
        with _sse_clients_lock:
            clients = len(_sse_clients)
        return {
            "clients": clients,
            "last_broadcast_ts": _last_broadcast_ts,
            "watermark": dict(_broadcast_watermarks),
            "watermark_initialized": _watermark_initialized,
        }


def create_router(
    publisher: NewsEventPublisher,
    handle_market_socket: Callable[[WebSocket], Any],
) -> APIRouter:
    router = APIRouter(tags=["realtime"])

    @router.get("/api/events")
    async def sse_events(_: Request) -> StreamingResponse:
        client: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=publisher.queue_size)  # type: ignore[attr-defined]
        publisher.add_client(client)
        loop = asyncio.get_running_loop()
        events: asyncio.Queue[tuple[str, dict[str, Any] | None]] = asyncio.Queue()
        stopped = threading.Event()

        def pump() -> None:
            while not stopped.is_set():
                try:
                    item = client.get(timeout=15)
                except queue.Empty:
                    asyncio.run_coroutine_threadsafe(events.put(("ping", None)), loop)
                    continue
                if item.get("type") == "shutdown":
                    break
                asyncio.run_coroutine_threadsafe(events.put(("data", item)), loop)

        threading.Thread(target=pump, daemon=True).start()

        async def stream():
            yield 'event: connected\ndata: {"type":"connected"}\n\n'
            try:
                while True:
                    kind, item = await events.get()
                    if kind == "ping":
                        yield ": ping\n\n"
                    else:
                        yield f"event: news\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
            finally:
                stopped.set()
                publisher.remove_client(client)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"
        })

    @router.get("/api/sse/health")
    def sse_health() -> dict[str, Any]:
        return publisher.health()

    @router.websocket("/ws/market")
    async def market_socket(websocket: WebSocket) -> None:
        await handle_market_socket(websocket)

    return router


async def poll_events(publisher: NewsEventPublisher) -> None:
    """Publish tick-triggered news with a periodic recovery poll."""
    last_tick = publisher.tick_mtime()
    elapsed = 0.0
    while True:
        try:
            await asyncio.sleep(SSE_TICK_POLL_INTERVAL)
            elapsed += SSE_TICK_POLL_INTERVAL
            tick = publisher.tick_mtime()
            triggered = bool(tick) and tick != last_tick
            if triggered:
                last_tick = tick
            if triggered or elapsed >= SSE_SAFETY_POLL_INTERVAL:
                elapsed = 0.0
                await asyncio.to_thread(publisher.publish_pending)
        except asyncio.CancelledError:
            return
