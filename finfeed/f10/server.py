#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同花顺 F10 个股资料 —— FastAPI 服务入口。

提供与独立版 f10-Web 一致的 HTTP 接口，挂载到 FinFeed 主应用时
使用前缀 ``/api/f10``；模块抓取全局串行 + TTL 缓存（复用 f10data），
避免并发抓取触发风控。

端点：
- GET  /api/f10/health   运行状态（模块元信息）
- GET  /api/f10/meta     模块清单 / 版本 / 缓存 TTL
- GET  /api/f10/search?kw  股票搜索建议
- GET  /api/f10/module?code=&mid=&idx=&refresh= 抓取一个 F10 模块并返回结构化 JSON

支持独立运行：``python -m finfeed.f10``（127.0.0.1，默认端口取自
模块内 config.json 的 ``port``，可用 --port 覆盖）。
"""

from __future__ import annotations

import argparse
import logging
import webbrowser
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from . import MODULES, WEB_DIR, fetch_module, meta, suggest
from .f10data import CFG, ModuleFetchError, clear_cache

logger = logging.getLogger("finfeed.f10")


def create_router(prefix: str = "/api/f10") -> APIRouter:
    """构造 F10 模块的 FastAPI 路由。

    ``prefix`` 供主应用挂载时改写（如 ``/api/f10``）；
    独立运行或以其他前缀挂载时传入对应值。
    """
    router = APIRouter(prefix=prefix, tags=["f10"])

    @router.get("/health")
    def health() -> dict[str, Any]:
        """模块运行状态与模块清单。"""
        return {"ok": True, **meta(), "module_count": len(MODULES)}

    @router.get("/meta")
    def meta_endpoint() -> dict[str, Any]:
        return {"ok": True, **meta()}

    @router.get("/search")
    def search(kw: str = Query("", max_length=64)) -> dict[str, Any]:
        """股票搜索建议（东方财富 suggest，统一走 f10data.suggest）。"""
        return {"ok": True, "results": suggest(kw.strip())}

    @router.get("/module")
    def module(
        code: str = Query("", max_length=16),
        mid: str = Query("", max_length=8),
        idx: int = Query(-1),
        refresh: int = Query(0),
    ) -> dict[str, Any]:
        """抓取一个 F10 模块并返回结构化 JSON（默认走缓存）。"""
        try:
            payload = fetch_module(idx, code, mid, refresh=bool(refresh))
            return payload
        except ModuleFetchError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    @router.post("/cache/clear")
    def cache_clear() -> dict[str, Any]:
        """清空模块缓存（调试用）。"""
        clear_cache()
        return {"ok": True}

    return router


def _run_standalone(port: int) -> None:
    """独立起服（python -m finfeed.f10）。"""
    import uvicorn

    app = __import__("fastapi").FastAPI(
        title="FinFeed · 同花顺 F10",
        description="同花顺 F10 个股资料（独立模块）",
    )
    app.include_router(create_router("/api/f10"))
    app.mount("/f10", __import__("fastapi").staticfiles.StaticFiles(
        directory=str(WEB_DIR), html=True), name="f10")

    url = f"http://127.0.0.1:{port}/f10/"
    print("=" * 56)
    print("  FinFeed · 同花顺 F10 个股资料")
    print(f"  页面: {url}")
    print(f"  引擎: 内置 F10 抓取引擎 v{meta()['version']} · "
          f"{len(MODULES)} 个模块（串行 + TTL 缓存）")
    print("  按 Ctrl+C 停止")
    print("=" * 56)
    if port != 0:
        webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=port)


def main() -> None:
    ap = argparse.ArgumentParser(description="FinFeed · 同花顺 F10 独立服务")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    port = args.port if args.port is not None else int(CFG.get("port", 8653))
    if args.no_open:
        # 简单处理：仍是独立进程，不自动开浏览器
        pass
    _run_standalone(port)


if __name__ == "__main__":
    main()
