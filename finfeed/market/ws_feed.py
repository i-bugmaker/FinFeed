#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WebSocket 行情推送服务

为前端提供稳定的行情实时推送通道，独立于既有 SSE（SSE 仅用于新闻增量）。

特性
----
- **连接管理**：以 ``WebSocket`` 对象为键维护在线客户端集合，连接/断开自动登记与清理。
- **心跳保活**：服务端每 ``HEARTBEAT`` 秒向每个客户端发 ``ping``；客户端须回 ``pong``。
  超过 ``HEARTBEAT_TIMEOUT`` 未收到 ``pong`` 的僵尸连接会被主动关闭，避免资源泄漏。
- **消息解析**：约定 JSON 文本协议，按 ``type`` 分发（hello / snapshot / ping / pong / alert）。
  非 JSON 或未知类型一律忽略，绝不中断连接。
- **异常恢复**：所有 ``send`` / ``receive`` 均包 try/except，单个客户端异常只将其剔除，
  不影响其它客户端与广播循环；广播循环整体再包一层兜底，不会因异常退出。
- **数据来源容错**：默认从本地行情数据层（``market_sentiment_daily`` / 涨停池 / 事实总览）
  轮询快照并广播；任意一张表缺失或查询异常都降级为空字段，服务照常运行。
- **优雅启停**：``start()`` / ``stop()`` 对接 FastAPI 生命周期；``stop`` 关闭全部连接。

协议（文本 JSON）：
  服务端 -> 客户端：
    {"type":"hello","server_time":<float>}
    {"type":"snapshot","data":{...}}          # 行情快照（每 PUSH_INTERVAL 推送）
    {"type":"ping"}                            # 心跳
    {"type":"alert","data":{...}}             # 实时告警（采集失败时）
  客户端 -> 服务端：
    {"type":"pong"}                            # 对服务端 ping 的应答
    {"type":"ping"}                            # 客户端主动探活，服务端回 pong
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("news_monitor")

# 推送节奏（秒）
PUSH_INTERVAL = 5.0        # 行情快照推送间隔
HEARTBEAT = 15.0           # 服务端心跳（ping）间隔
HEARTBEAT_TIMEOUT = 40.0   # 超过此时间未收到客户端 pong 则判定僵尸并关闭


class MarketWSService:
    """行情 WebSocket 推送服务（模块级单例 ``service``）。"""

    def __init__(self):
        # FastAPI 单事件循环语义下所有访问都在事件循环内，无需额外加锁；
        # 跨线程调用（如采集线程触发告警）通过「待推缓冲」在广播循环内统一下发。
        self._clients: Dict[int, Dict[str, Any]] = {}
        self._pending_alerts: List[Dict[str, Any]] = []
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> None:
        """启动后台广播循环（幂等）。必须在事件循环内调用（startup 钩子或首次连接）。"""
        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            self._loop = None
        if self.running:
            return
        self.running = True
        # 将采集失败告警回调接到本推送服务（幂等，且不依赖启动顺序：
        # 即便 on_event startup 未触发，首次 WebSocket 连接时的 ensure_started
        # 也会完成本接线，保证告警实时送达前端）。
        try:
            from finfeed.market import alerting as market_alerting

            market_alerting.manager.on_alert_callback = self.push_alert
            logger.info("采集失败告警 → WebSocket 推送回调已挂载")
        except Exception:  # noqa: BLE001
            pass
        try:
            self._task = asyncio.create_task(self._loop_broadcast())
            logger.info("行情 WebSocket 推送服务已启动")
        except RuntimeError:
            # 不在事件循环中（如测试环境）：延迟到首次连接时再启动
            self.running = False

    async def stop(self) -> None:
        """停止广播循环并关闭所有连接。"""
        self.running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        # 关闭所有客户端
        for cid in list(self._clients.keys()):
            await self._close_client(cid)
        self._clients.clear()
        logger.info("行情 WebSocket 推送服务已停止")

    def ensure_started(self) -> None:
        """在首次连接时若尚未启动则尝试启动（兼容非 startup 场景）。"""
        if not self.running:
            self.start()

    # ------------------------------------------------------------------
    # 连接处理（每个连接一个协程）
    # ------------------------------------------------------------------
    async def handle_connection(self, websocket) -> None:  # noqa: ANN001

        self.ensure_started()
        await websocket.accept()
        cid = id(websocket)
        self._clients[cid] = {
            "ws": websocket,
            "last_pong": time.time(),
            "connected_at": time.time(),
        }
        logger.info(f"行情 WS 客户端接入 cid={cid}，当前在线 {len(self._clients)}")
        try:
            # 握手后立即下发 hello + 首帧快照
            await self._send(websocket, {"type": "hello", "server_time": time.time()})
            snap = await asyncio.to_thread(self._build_payload)
            await self._send(websocket, {"type": "snapshot", "data": snap})
            # 接收循环：处理 pong / ping
            while True:
                try:
                    raw = await websocket.receive_text()
                except Exception:  # noqa: BLE001
                    break
                self._on_client_message(cid, raw)
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._clients.pop(cid, None)
            logger.info(f"行情 WS 客户端断开 cid={cid}，剩余 {len(self._clients)}")

    def _on_client_message(self, cid: int, raw: str) -> None:
        info = self._clients.get(cid)
        if not info:
            return
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return  # 非法 JSON 直接忽略
        t = msg.get("type")
        if t == "pong":
            info["last_pong"] = time.time()
        elif t == "ping":
            # 客户端主动探活，回 pong
            ws = info.get("ws")
            if ws is not None:
                asyncio.ensure_future(self._send(ws, {"type": "pong"}))

    # ------------------------------------------------------------------
    # 广播循环
    # ------------------------------------------------------------------
    async def _loop_broadcast(self) -> None:
        logger.info(
            f"行情 WS 广播循环已启动（推送间隔 {PUSH_INTERVAL}s / 心跳 {HEARTBEAT}s / 超时 {HEARTBEAT_TIMEOUT}s）"
        )
        while self.running:
            try:
                # 行情快照（线程内取数，避免阻塞事件循环）
                payload = await asyncio.to_thread(self._build_payload)
                await self._broadcast({"type": "snapshot", "data": payload})

                # 下发给所有在线客户端的待推告警（采集线程写入，此处统一Flush）
                if self._pending_alerts:
                    pending = self._pending_alerts[:]
                    self._pending_alerts.clear()
                    for rec in pending:
                        await self._broadcast({"type": "alert", "data": rec})

                # 心跳 + 僵尸清理
                now = time.time()
                for cid, info in list(self._clients.items()):
                    if now - info.get("last_pong", now) > HEARTBEAT_TIMEOUT:
                        await self._close_client(cid)
                        continue
                    if now - info.get("last_ping", 0) >= HEARTBEAT:
                        info["last_ping"] = now
                        ws = info.get("ws")
                        if ws is not None:
                            await self._send(ws, {"type": "ping"})
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.error(f"行情 WS 广播循环异常: {e}")
            # 固定间隔推送
            for _ in range(int(PUSH_INTERVAL * 10)):
                if not self.running:
                    break
                await asyncio.sleep(0.1)

    async def _broadcast(self, msg: Dict[str, Any]) -> None:
        if not self._clients:
            return
        dead: list[int] = []
        for cid, info in list(self._clients.items()):
            ws = info.get("ws")
            if ws is None:
                dead.append(cid)
                continue
            try:
                await self._send(ws, msg)
            except Exception:  # noqa: BLE001
                dead.append(cid)
        for cid in dead:
            await self._close_client(cid)

    async def _send(self, websocket, msg: Dict[str, Any]) -> None:
        try:
            await websocket.send_text(json.dumps(msg, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            raise e

    async def _close_client(self, cid: int) -> None:
        info = self._clients.pop(cid, None)
        if info is None:
            return
        ws = info.get("ws")
        try:
            if ws is not None:
                await ws.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # 实时告警（供 alerting.on_alert_callback 调用）
    # ------------------------------------------------------------------
    def push_alert(self, record: Dict[str, Any]) -> None:
        """把一条采集告警推送给所有在线客户端（线程安全）。

        写入待推缓冲，由广播循环在下一个周期统一下发。优势：
        - 跨线程安全（采集线程直接调用即可，无需事件循环引用）。
        - 即使告警发生在客户端连接之前，也会在客户端接入后的首个周期送达。
        """
        try:
            self._pending_alerts.append(record)
            if len(self._pending_alerts) > 1000:
                self._pending_alerts = self._pending_alerts[-1000:]
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # 快照构建（同步，在 to_thread 中执行）
    # ------------------------------------------------------------------
    def _build_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ts": time.time(),
            "trade_date": None,
            "sentiment": None,
            "limit_up": None,
            "overview": None,
            "alerts": [],
        }
        try:
            from finfeed.market import alerting as mk_alerting
            from finfeed.market import store as mk_store
            from finfeed.storage import sentiment_store as ss

            sn = None
            try:
                sn = ss.get_market_sentiment()
            except Exception:  # noqa: BLE001
                sn = None
            if sn:
                payload["sentiment"] = {
                    k: sn.get(k)
                    for k in (
                        "trade_date", "sentiment_index", "up_limit",
                        "down_limit", "breadth", "forum_heat", "news_sentiment",
                    )
                }
                td = sn.get("trade_date")
            else:
                td = mk_store.latest_date("market_sentiment_daily")
            payload["trade_date"] = td

            if td:
                try:
                    lu = mk_store.get_limit_pool(td, "up")
                    payload["limit_up"] = len(lu) if isinstance(lu, list) else None
                except Exception:  # noqa: BLE001
                    payload["limit_up"] = None

            try:
                ov = mk_store.get_fact_overview()
                if ov:
                    payload["overview"] = {
                        "tables": len(ov.get("tables", [])),
                        "boards": len(ov.get("boards", [])),
                    }
            except Exception:  # noqa: BLE001
                payload["overview"] = None

            try:
                payload["alerts"] = mk_alerting.get_recent(limit=10)
            except Exception:  # noqa: BLE001
                payload["alerts"] = []
        except Exception as e:  # noqa: BLE001
            logger.warning(f"行情 WS 快照构建异常（降级）: {e}")
        return payload


# 模块级单例
service = MarketWSService()


async def handle_connection(websocket) -> None:  # noqa: ANN001
    """WebSocket 端点处理函数（委托给模块级单例）。"""
    await service.handle_connection(websocket)


def start() -> None:
    service.start()


async def stop() -> None:
    await service.stop()


def push_alert(record: Dict[str, Any]) -> None:
    service.push_alert(record)
