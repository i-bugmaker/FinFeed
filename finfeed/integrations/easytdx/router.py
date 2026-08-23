#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""easy-tdx 模块的 FastAPI 路由。

端点：
- GET  /api/easytdx/meta      功能注册表（分组 + 功能 + 参数 schema），供前端渲染
- POST /api/easytdx/run       提交一次功能调用，返回 task_id（后台线程执行）
- GET  /api/easytdx/task/{id} 轮询任务状态 / 日志 / 进度 / 结果
- GET  /api/easytdx/tasks     最近任务列表
- GET  /api/easytdx/download/{id}  下载文件类结果
- GET  /api/easytdx/strategies  回测策略列表（含参数 schema，供回测表单动态渲染）
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import service
from .registry import FUNCTIONS, GROUPS, get_function, get_groups_with_functions

logger = logging.getLogger("easytdx_router")

router = APIRouter(prefix="/api/easytdx", tags=["easytdx"])


class RunRequest(BaseModel):
    function: str
    params: dict[str, Any] = {}


@router.get("/meta")
def meta():
    """返回功能注册表，供前端动态渲染导航与参数表单。"""
    return {
        "groups": get_groups_with_functions(),
        "functions": FUNCTIONS,
        "group_meta": GROUPS,
    }


@router.get("/strategies")
def strategies():
    """返回回测注册表中的策略及其参数 schema。"""
    try:
        from easy_tdx.backtest.strategies import get_registry
        reg = get_registry()
        out = []
        # RegisteredStrategy.to_schema() 已返回可序列化的干净结构
        for rs in reg.all():
            schema = rs.to_schema()
            params = []
            for pp in schema.get("params", []):
                params.append({
                    "name": pp["name"],
                    "label": pp.get("label", pp["name"]),
                    "type": pp.get("type", "int"),
                    "default": pp.get("default", None),
                    "min": pp.get("min_value", None),
                    "max": pp.get("max_value", None),
                })
            out.append({
                "name": schema["name"],
                "label": schema.get("label", schema["name"]),
                "description": schema.get("description", ""),
                "params": params,
            })
        return {"strategies": out}
    except Exception as e:  # noqa: BLE001
        logger.exception("list strategies failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run")
def run(req: RunRequest):
    func_def = get_function(req.function)
    if not func_def:
        raise HTTPException(status_code=404, detail=f"未知功能: {req.function}")
    try:
        task = service.create_task(req.function, req.params)
        return task
    except Exception as e:  # noqa: BLE001
        logger.exception("create task failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/task/{task_id}")
def task(task_id: str):
    t = service.get_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 复制避免返回内部对象
    return {
        "task_id": t["task_id"],
        "func_id": t["func_id"],
        "func_label": t["func_label"],
        "status": t["status"],
        "progress": t["progress"],
        "logs": t["logs"],
        "result": t["result"],
        "error": t["error"],
        "started_at": t["started_at"],
        "finished_at": t["finished_at"],
    }


@router.get("/tasks")
def tasks(limit: int = Query(20, ge=1, le=100)):
    return {"tasks": service.list_tasks(limit)}


@router.get("/download/{task_id}")
def download(task_id: str):
    t = service.get_task(task_id)
    if not t or not t.get("file_path"):
        raise HTTPException(status_code=404, detail="文件不存在")
    fpath = Path(t["file_path"])
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="文件已失效")
    return FileResponse(
        str(fpath),
        filename=os.path.basename(str(fpath)),
        media_type="application/octet-stream",
    )
