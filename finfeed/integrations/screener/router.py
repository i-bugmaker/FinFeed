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

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from . import service

logger = logging.getLogger("screener_router")

router = APIRouter(prefix="/api/screener", tags=["screener"])


class RunRequest(BaseModel):
    top: int = 50
    technical: bool = False
    top_tech: int = 200
    boards: dict | None = None        # 板块白名单：{"main":true,"kcb":true,"cyb":true,"bj":false}


@router.get("/config")
def config():
    """返回选股配置与方法论说明。"""
    return service.get_config()


@router.post("/run")
def run(req: RunRequest):
    """提交一次选股任务。"""
    try:
        params = {
            "top": req.top,
            "technical": req.technical,
            "top_tech": req.top_tech,
            "boards": req.boards,
        }
        return service.create_task(params)
    except RuntimeError as e:  # 并发上限等业务性拒绝
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("create screener task failed")
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
