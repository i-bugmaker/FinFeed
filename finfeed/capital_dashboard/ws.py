# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏 —— WebSocket 实时推送通道。

将原本前端每 5s 拉取 7 个独立 REST 接口，收敛为**单个 WebSocket 连接、服务端批量推送**：
大屏建立 WS 后，后端按刷新节奏把「指数/宽度/个股榜/板块榜/轮动/异常」打包成一条
消息下发，前端仅做渲染。延迟由「采集耗时 + 轮询间隔(8s) + 前端轮询(5s)」降至
「采集耗时 + 推送检查(≤2s)」，且请求量显著下降。

实现要点：
- 采用「服务端增量检查 + WS 推送」而非跨线程事件，规避后台采集线程与事件循环
  的耦合风险；推送检查周期为 ``min(2s, REFRESH_INTERVAL/2)``，数据变化才下发。
- WS 不可用时前端自动回退到 REST 轮询（见 ``web/index.html``），保证可用性。
- 连接管理：异常/断开均被静默处理，单个客户端故障不影响其余客户端与采集线程。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import config
from .observability import tracker as _signal_tracker

logger = logging.getLogger("finfeed.capital_dashboard.ws")

ws_router = APIRouter()


def _build_payload() -> dict | None:
    """从内存快照构建一条批量推送负载（字段与 REST 接口对齐）。"""
    from . import funds
    from .server import store  # 延迟导入，避免与 server 的循环依赖
    snap = store.get_snapshot()
    if snap is None:
        return None
    rot = store.get_rotation()
    anom = store.get_anomalies()
    breadth = asdict(snap.breadth)
    stats = asdict(snap.stats)

    def board_list(bt: str, limit: int):
        return [
            asdict(b) for b in snap.boards
            if b.board_type == bt
        ][:limit]

    def stock_list(direction: str, limit: int):
        s = sorted(snap.stocks, key=lambda x: x.main_net, reverse=(direction == "in"))
        out = []
        for x in s[:limit]:
            d = asdict(x)
            out.append(d)
        return out

    return {
        "ts": snap.ts,
        "ts_label": snap.ts_label,
        "last_refresh": store.health().get("last_refresh_ts"),
        "indices": [asdict(i) for i in snap.indices],
        "breadth": breadth,
        "stats": stats,
        "stock_in": stock_list("in", config.STOCK_TOP_N),
        "stock_out": stock_list("out", config.STOCK_TOP_N),
        "boards_hy": board_list("HY", config.BOARD_TOP_N),
        "boards_gn": board_list("GN", min(config.GN_RANKING_TOP, config.BOARD_TOP_N)),
        "funds": funds.get_snapshot(),   # ETF/基金资金排行（东财 push2 独立链路）
        "rotation": asdict(rot) if rot else None,
        "anomalies": anom.to_dict() if anom else None,
        "signal_stats": _signal_tracker.summary(),
        "health": store.health(),
    }


@ws_router.websocket("/ws")
async def capital_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.info("资金流 WS 客户端接入")
    last_ts = None
    try:
        while True:
            payload = _build_payload()
            if payload and payload.get("ts") != last_ts:
                await websocket.send_json(payload)
                last_ts = payload.get("ts")
            await asyncio.sleep(max(0.5, config.REFRESH_INTERVAL / 2.0))
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("资金流 WS 连接异常断开: %s", exc)
