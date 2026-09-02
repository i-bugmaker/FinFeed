#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""告警推送模块 — FastAPI 路由（前缀 /api/alerts）。

端点总览
--------
推送渠道：
- GET    /webhooks              渠道列表
- POST   /webhooks              新增渠道
- PUT    /webhooks/{id}         更新渠道
- DELETE /webhooks/{id}         删除渠道
- POST   /webhooks/{id}/test    发送测试消息

订阅与设置：
- GET/PUT /settings             全局设置（总开关/基准阈值/动态调节）
- GET/POST /topics              主题订阅列表 / 新增
- PUT/DELETE /topics/{id}       更新 / 删除主题
- GET    /watchlist             自选股订阅（复用股票监控模块，只读视图）

运行状态：
- GET    /regime                当前市场状态与动态阈值倍率
- GET    /logs                  最近推送日志
- GET    /calibration           最近一次情感闭环校准结果
- POST   /calibration/run       手动触发一次校准（后台线程执行）
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from finfeed.alerts import store
from finfeed.alerts.webhook import CHANNEL_LABELS, make_test_news, send_webhook_news
from finfeed.market.alerts import regime_summary

logger = logging.getLogger("news_monitor")

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


# 请求体
class WebhookPayload(BaseModel):
    name: str = ""
    type: str
    url: str
    extra: str = ""
    enabled: bool = True
    min_importance: float = 0.0
    quiet_start: str = ""
    quiet_end: str = ""


class WebhookPatch(BaseModel):
    name: str | None = None
    type: str | None = None
    url: str | None = None
    extra: str | None = None
    enabled: bool | None = None
    min_importance: float | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None


class SettingsPayload(BaseModel):
    enabled: bool | None = None
    base_importance: float | None = Field(default=None, ge=0, le=10)
    watchlist_min_importance: float | None = Field(default=None, ge=0, le=10)
    use_regime: bool | None = None


class TopicPayload(BaseModel):
    name: str
    keywords: list[str] = Field(default_factory=list)
    description: str = ""
    is_enabled: bool | None = None


class TopicPatch(BaseModel):
    name: str | None = None
    keywords: list[str] | None = None
    description: str | None = None
    is_enabled: bool | None = None


# 推送渠道
@router.get("/channels")
def list_channels():
    """渠道类型与展示名（供前端下拉）。"""
    return {"channels": [{"type": t, "label": label} for t, label in CHANNEL_LABELS.items()]}


@router.get("/webhooks")
def list_webhooks():
    return {"webhooks": store.list_webhooks()}


@router.post("/webhooks")
def create_webhook(payload: WebhookPayload):
    created = store.create_webhook(payload.model_dump())
    if not created:
        raise HTTPException(status_code=400, detail="创建失败：类型不支持或 URL 为空")
    return {"webhook": created}


@router.put("/webhooks/{webhook_id}")
def update_webhook(webhook_id: int, payload: WebhookPatch):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = store.update_webhook(webhook_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="渠道不存在或更新失败")
    return {"webhook": updated}


@router.delete("/webhooks/{webhook_id}")
def delete_webhook(webhook_id: int):
    if not store.delete_webhook(webhook_id):
        raise HTTPException(status_code=404, detail="渠道不存在")
    return {"ok": True}


@router.post("/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: int):
    """向指定渠道发送一条测试消息。"""
    cfg = store.get_webhook(webhook_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="渠道不存在")
    res = await send_webhook_news([make_test_news()], [cfg])
    details = res.get("details") or []
    ok = bool(res.get("success"))
    return {
        "ok": ok,
        "message": "测试消息已发送，请到群/手机确认" if ok else f"发送失败：{details[0].get('error', '') if details else '未知错误'}",
        "details": details,
    }


# 设置与订阅
@router.get("/settings")
def get_settings():
    return {"settings": store.get_settings()}


@router.put("/settings")
def put_settings(payload: SettingsPayload):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    return {"settings": store.update_settings(data)}


@router.get("/topics")
def list_topics():
    return {"topics": store.list_topics()}


@router.post("/topics")
def create_topic(payload: TopicPayload):
    data = payload.model_dump()
    enabled = data.pop("is_enabled", None)
    created = store.create_topic(data["name"], data["keywords"], data["description"])
    if not created:
        raise HTTPException(status_code=400, detail="创建失败：名称与关键词不能为空")
    if enabled is False:
        created = store.update_topic(created["id"], {"is_enabled": False})
    return {"topic": created}


@router.put("/topics/{topic_id}")
def update_topic(topic_id: int, payload: TopicPatch):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = store.update_topic(topic_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="主题不存在")
    return {"topic": updated}


@router.delete("/topics/{topic_id}")
def delete_topic(topic_id: int):
    if not store.delete_topic(topic_id):
        raise HTTPException(status_code=404, detail="主题不存在")
    return {"ok": True}


@router.get("/watchlist")
def get_watchlist():
    """自选股订阅只读视图（管理入口在「股票监控」页）。"""
    from finfeed.alerts.subscription import get_watchlist as _gw

    return {"stocks": _gw()}


# 运行状态
@router.get("/regime")
def get_regime():
    """当前市场状态与动态阈值（通知设置页徽标 + 阈值说明）。"""
    try:
        return {"regime": regime_summary()}
    except Exception as e:
        logger.warning(f"读取市场状态失败: {e}")
        return {"regime": {"trade_date": "", "regime": "normal",
                            "threshold_multiplier": 1.0, "note": "市场状态数据暂不可用，使用基准阈值"}}


@router.get("/logs")
def get_logs(limit: int = 30):
    limit = max(1, min(limit, 200))
    return {"logs": store.recent_push_log(limit)}


@router.get("/calibration")
def get_calibration():
    return {"calibration": store.calibration_latest()}


@router.post("/calibration/run")
def run_calibration():
    """手动触发情感闭环校准（后台线程执行，结果经 GET /calibration 查询）。"""
    def _job():
        try:
            from finfeed.analysis.crossref import run_calibrate, save_calibration_result
            result = run_calibrate()
            save_calibration_result(result)
            logger.info(f"手动情感校准完成：样本 {result.get('sample', 0)}")
        except Exception as e:
            logger.error(f"手动情感校准失败: {e}", exc_info=True)

    threading.Thread(target=_job, daemon=True, name="alerts-calibrate").start()
    return {"ok": True, "message": "校准已启动（离线批处理，约需数十秒）"}
