#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""股票监控模块 — FastAPI 路由（前缀 /api/stock-monitor）。

端点总览
--------
监控列表管理：
- GET    /stocks                    查看监控列表
- POST   /stocks                    文本批量导入（含手动单个，body: {text}）
- POST   /stocks/import/image       截图 OCR 批量导入（multipart: file）
- PUT    /stocks/{code}             编辑备注（body: {note}）
- DELETE /stocks/{code}             删除监控

舆情聚合：
- GET    /feed                      分组聚合（?codes=&since_ts=&limit= 离线补全）
- GET    /feed/stream               SSE 实时推送（?codes=，事件 feed）
- POST   /refresh                   立即刷新外部消息
- GET    /status                    模块运行状态

AI 分析：
- POST   /analyze/{code}            提交分析任务
- GET    /analyze/task/{aid}        查询任务状态/结果
- GET    /analyze/{code}/latest     最近一次分析
- GET    /analyze/{code}/history    历史分析列表
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from finfeed.stock_monitor import service, store
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("stock_monitor")

router = APIRouter(prefix="/api/stock-monitor", tags=["stock-monitor"])

SSE_POLL_INTERVAL = 2.5


# 请求体
class ImportTextRequest(BaseModel):
    text: str


class UpdateStockRequest(BaseModel):
    note: str = ""


# 监控列表管理
@router.get("/stocks")
def list_stocks():
    store.ensure_tables()
    return {"stocks": store.list_stocks()}


# 智能联想（手动输入名称/代码/拼音）
@router.get("/suggest")
def suggest(
    q: str = Query("", description="输入片段：代码/名称/拼音简称"),
    limit: int = Query(8, ge=1, le=20),
):
    """导入框智能联想：代码前缀 / 名称 / 拼音简称即时匹配。"""
    store.ensure_tables()
    return {"suggestions": service.suggest_stocks(q, limit)}


@router.post("/stocks")
def import_text(req: ImportTextRequest):
    """文本批量导入（手动输入单个代码同样走此入口）。"""
    if not (req.text or "").strip():
        raise HTTPException(status_code=400, detail="导入内容不能为空")
    return service.parse_and_import(req.text)


@router.post("/stocks/import/image")
async def import_image(file: UploadFile = File(...)):
    """截图批量导入：OCR 识别股票代码后校验入库。"""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="图片内容为空")
    result = service.import_image(data)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "OCR 识别失败"))
    return result


@router.put("/stocks/{code}")
def update_stock(code: str, req: UpdateStockRequest):
    if not store.update_stock_note(code, req.note):
        raise HTTPException(status_code=404, detail="监控股票不存在")
    return {"ok": True, "code": code, "note": req.note}


@router.delete("/stocks/{code}")
def delete_stock(code: str):
    if not store.delete_stock(code):
        raise HTTPException(status_code=404, detail="监控股票不存在")
    return {"ok": True, "deleted": code}


# 舆情聚合
def _parse_codes(codes: str) -> list[str] | None:
    if not codes or codes.strip().lower() in ("", "all"):
        return None
    return [c for c in (s.strip() for s in codes.split(",")) if c]


@router.get("/feed")
def feed(
    codes: str = Query("", description="逗号分隔的股票代码；空 = 全部监控股票"),
    since_ts: int = Query(0, ge=0, description="只返回该时间戳之后的消息（离线补全）"),
    limit: int = Query(60, ge=10, le=200, description="每只股票返回条数上限"),
):
    """按股票分组聚合舆情（系统内 + 系统外）。

    前端离线补全：页面加载时以 localStorage 记忆的 last_seen_ts 作为
    since_ts 调用本接口，即可一次性取回离线期间遗漏的全部消息。
    """
    store.ensure_tables()
    return service.aggregate_feed(
        codes=_parse_codes(codes), since_ts=since_ts, limit_per_code=limit
    )


@router.get("/feed/stream")
async def feed_stream(codes: str = Query("", description="逗号分隔的股票代码；空 = 全部")):
    """SSE 实时推送：系统内/外两路消息的增量，事件名 `feed`。"""
    store.ensure_tables()
    wanted = _parse_codes(codes)
    stock_codes = [s["code"] for s in store.list_stocks() if not wanted or s["code"] in set(wanted)]

    try:
        from finfeed.storage.database import db_get_max_news_id

        internal_wm = db_get_max_news_id()
    except Exception:  # noqa: BLE001
        internal_wm = 0
    external_wm = store.get_external_max_id(stock_codes)

    async def stream():
        nonlocal internal_wm, external_wm
        yield (
            'event: connected\ndata: {"type":"connected","codes":'
            + json.dumps(stock_codes, ensure_ascii=False)
            + "}\n\n"
        )
        while True:
            try:
                result = await asyncio.to_thread(
                    service.realtime_new_items, stock_codes, internal_wm, external_wm
                )
                internal_wm = result["internal_watermark"]
                external_wm = result["external_watermark"]
                if result["items"]:
                    payload = {
                        "items": result["items"],
                        "count": len(result["items"]),
                        "ts": now_bj().timestamp(),
                    }
                    yield f"event: feed\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                else:
                    yield ": ping\n\n"
            except asyncio.CancelledError:
                return
            except Exception as e:  # noqa: BLE001
                logger.warning("SSE 轮询异常: %s", e)
                yield ": error\n\n"
            await asyncio.sleep(SSE_POLL_INTERVAL)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/refresh")
def refresh_now():
    """立即为全部监控股票刷新一轮外部消息。"""
    store.ensure_tables()
    return {"ok": True, **service.worker.refresh_now()}


@router.get("/status")
def status():
    return service.module_status()


# AI 分析
@router.post("/analyze/{code}")
def analyze(code: str):
    """提交一次 AI 智能分析（后台线程执行，轮询 /analyze/task/{id} 获取结果）。"""
    result = service.submit_analysis(code)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "提交分析失败"))
    return result


@router.get("/analyze/task/{analysis_id}")
def analyze_task(analysis_id: int):
    row = store.get_analysis(analysis_id)
    if not row:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    return row


@router.get("/analyze/{code}/latest")
def analyze_latest(code: str):
    return {"analysis": store.get_latest_analysis(code)}


@router.get("/analyze/{code}/history")
def analyze_history(code: str, limit: int = Query(10, ge=1, le=50)):
    return {"analyses": store.list_analyses(code, limit)}
