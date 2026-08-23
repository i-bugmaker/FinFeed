"""HTTP adapter for the LLM domain API."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from finfeed.llm import api as llm_api


def create_router() -> APIRouter:
    router = APIRouter(tags=["llm"])

    @router.get("/api/llm/report/export")
    def export_report(id: int = Query(0), fmt: str = Query("md")) -> Response:
        result = llm_api.export_report(id, fmt)
        if not result:
            raise HTTPException(status_code=404, detail="not found")
        filename, body, content_type = result
        return Response(content=body, media_type=content_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @router.api_route("/api/llm/{rest:path}", methods=["GET", "POST"])
    async def dispatch(request: Request, rest: str) -> JSONResponse:
        if request.method == "GET":
            result = llm_api.handle_get(request.url.path, parse_qs(request.url.query))
        else:
            body = await request.body()
            result = llm_api.handle_post(request.url.path, json.loads(body.decode("utf-8")) if body else {})
        if result is None:
            raise HTTPException(status_code=404, detail="not found")
        return JSONResponse(content=result[1], status_code=result[0], headers={"Cache-Control": "no-cache"})

    return router
