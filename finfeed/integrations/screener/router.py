#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智能选股 FastAPI 路由。

端点：
- GET  /api/screener/config   评分方法论与配置权重
- POST /api/screener/run      提交一次选股任务（后台线程执行）
- GET  /api/screener/task/{id} 轮询任务状态 / 进度 / 结果
- GET  /api/screener/tasks    最近任务列表
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel

from . import service

logger = logging.getLogger("screener_router")

router = APIRouter(prefix="/api/screener", tags=["screener"])


class RunRequest(BaseModel):
    top: int = 50
    technical: bool = False
    top_tech: int = 200
    boards: dict | None = None        # 板块白名单：{"main":true,"kcb":true,"cyb":true,"bj":false}
    request: dict | None = None        # 结构化选股请求（ScreenerRequest，见设计文档 §4.1）
    template: str | None = None        # 应用已存模板名


class CompareRequest(BaseModel):
    a: dict
    b: dict
    technical: bool = False
    top: int = 200


class TemplateRequest(BaseModel):
    name: str
    request: dict


class EvaluateRequest(BaseModel):
    request: dict | None = None        # 可选：结构化选股请求覆盖引擎模式
    end_date: str | None = None        # 评估截止日（含）
    horizon: int | None = None         # 前瞻收益期限
    step: int = 1                      # 截面间隔


@router.get("/config")
def config():
    """返回选股配置与方法论说明。"""
    return service.get_config()


@router.post("/run")
def run(req: RunRequest):
    """提交一次选股任务（支持结构化 ScreenerRequest）。"""
    try:
        params = {
            "top": req.top,
            "technical": req.technical,
            "top_tech": req.top_tech,
            "boards": req.boards,
            "request": req.request,
            "template": req.template,
        }
        return service.create_task(params)
    except RuntimeError as e:  # 并发上限等业务性拒绝
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("create screener task failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/compare")
def compare(req: CompareRequest):
    """策略对比：同一快照下跑两套规则，返回结果与差异摘要。"""
    try:
        return service.run_compare(req.a, req.b, technical=req.technical, top_n=req.top)
    except Exception as e:  # noqa: BLE001
        logger.exception("screener compare failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/templates")
def templates():
    """列出已存选股模板。"""
    return {"templates": service.list_templates()}


@router.post("/templates")
def save_template(req: TemplateRequest):
    """保存选股模板。"""
    if not req.name:
        raise HTTPException(status_code=400, detail="模板名不能为空")
    return service.save_template(req.name, req.request)


@router.delete("/templates/{name}")
def delete_template(name: str):
    """删除选股模板。"""
    ok = service.delete_template(name)
    if not ok:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"deleted": name}


@router.post("/evaluate")
def evaluate(req: EvaluateRequest):
    """P6 评估闭环：walk-forward 评估当前引擎（RankIC/ICIR/分层/IR + 失效监控）。"""
    try:
        from finfeed.screener import request as request_mod
        from finfeed.screener.config import load_config

        cfg = (request_mod.build_config(
            request_mod.ScreenerRequest.from_dict(req.request), load_config())
            if req.request else load_config())
        return service.run_evaluation(
            cfg=cfg, end_date=req.end_date, horizon=req.horizon, step=req.step)
    except Exception as e:  # noqa: BLE001
        logger.exception("screener evaluate failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/task/{task_id}")
def task(task_id: str):
    """查询任务状态与结果。"""
    t = service.get_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "task_id": t["task_id"],
        "func_id": t["func_id"],
        "func_label": t["func_label"],
        "status": t["status"],
        "progress": t["progress"],
        "logs": t["logs"],
        "result": t["result"],
        "error": t["error"],
        "error_code": t.get("error_code"),
        "started_at": t["started_at"],
        "finished_at": t["finished_at"],
    }


@router.get("/tasks")
def tasks(limit: int = Query(20, ge=1, le=100)):
    """最近任务列表。"""
    return {"tasks": service.list_tasks(limit)}
