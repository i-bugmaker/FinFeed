"""HTTP adapter for the economic-calendar domain API."""

from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from finfeed.ecal import api as calendar_api

logger = logging.getLogger("news_monitor")


def create_router() -> APIRouter:
    router = APIRouter(tags=["calendar"])

    @router.get("/api/calendar/export", response_model=None)
    def export_events(request: Request):
        try:
            payload, content_type, filename = calendar_api.export_events(parse_qs(request.url.query))
            return Response(content=payload, media_type=content_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Calendar export failed", exc_info=exc)
            return JSONResponse(content={"error": str(exc)}, status_code=500, headers={"Cache-Control": "no-cache"})

    @router.api_route("/api/calendar/{rest:path}", methods=["GET", "POST"], response_model=None)
    async def dispatch(request: Request, rest: str):
        if request.method == "GET":
            result = calendar_api.handle_get(request.url.path, parse_qs(request.url.query))
        else:
            body = await request.body()
            result = calendar_api.handle_post(request.url.path, json.loads(body.decode("utf-8")) if body else {})
        if result is None:
            raise HTTPException(status_code=404, detail="not found")
        return JSONResponse(content=result[1], status_code=result[0], headers={"Cache-Control": "no-cache"})

    return router
