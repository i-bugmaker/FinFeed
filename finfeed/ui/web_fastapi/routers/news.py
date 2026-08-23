"""News-feed HTTP routes; business coordination lives in ``application``."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

from finfeed.application.news_service import NewsService
from finfeed.storage.database import (
    db_get_all_stock_names,
    db_get_date_range,
    db_get_news_by_id,
    db_mark_read,
    db_query_news,
    db_search_news,
    db_toggle_favorite,
)
from finfeed.ui.web.shared import (
    _build_news_response,
    _cache_get,
    _cache_set,
    _get_cached_sources,
    _get_flash_article_display_names,
    invalidate_api_cache,
)

logger = logging.getLogger("news_monitor")


def create_router(parse_params: Callable[[dict[str, list[str]]], dict[str, Any]], qdict: Callable[[Request], dict[str, list[str]]]) -> APIRouter:
    router = APIRouter(tags=["news"])
    service = NewsService(
        db_query_news,
        _build_news_response, _cache_get, _cache_set, invalidate_api_cache,
    )

    def response(data: Any, status: int = 200, max_age: int = 0) -> JSONResponse:
        return JSONResponse(content=data, status_code=status, headers={"Cache-Control": f"private, max-age={max_age}" if max_age else "no-cache"})

    def category(request: Request, kind: str, names: list[str]) -> JSONResponse:
        try:
            params = parse_params(qdict(request))
            if params["source"] and params["source"] not in names:
                params["source"] = None
            key = f"{kind}:{json.dumps(params, sort_keys=True, default=str)}"
            return response(service.list_category(category=kind, params=params, display_names=names, cache_key=key), max_age=1)
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s API failed", kind, exc_info=exc)
            return response({"error": str(exc)}, status=500)

    @router.get("/api/flash")
    def flash(request: Request) -> JSONResponse:
        names, _ = _get_flash_article_display_names()
        return category(request, "flash", names)

    @router.get("/api/articles")
    def articles(request: Request) -> JSONResponse:
        _, names = _get_flash_article_display_names()
        return category(request, "article", names)

    @router.get("/api/sentiment")
    def sentiment(request: Request) -> JSONResponse:
        _, _, names, _, _ = _get_cached_sources()
        return category(request, "forum", names)

    @router.get("/api/favorites")
    def favorites(request: Request) -> JSONResponse:
        try:
            params = parse_params(qdict(request))
            items, total = db_query_news(limit=params["page_size"], offset=params["offset"], keyword=params["keyword"], is_favorite=True)
            return response(_build_news_response(items, total, params["offset"], params["page_size"], []))
        except Exception as exc:  # noqa: BLE001
            return response({"error": str(exc)}, status=500)

    @router.get("/api/stock_names")
    def stock_names() -> JSONResponse:
        cached = _cache_get("stock_names_map")
        if cached is not None:
            return response(cached, max_age=300)
        try:
            names = db_get_all_stock_names()
            if not names:
                from finfeed.analysis.stock_names import STOCK_NAMES
                names = dict(STOCK_NAMES)
            result = {"stock_names": names}
            _cache_set("stock_names_map", result)
            return response(result, max_age=300)
        except Exception as exc:  # noqa: BLE001
            return response({"stock_names": {}, "error": str(exc)}, status=500)

    @router.get("/api/daterange")
    def date_range() -> dict[str, Any]:
        minimum, maximum, dates = db_get_date_range()
        return {"min": minimum, "max": maximum, "dates": dates}

    @router.get("/api/search")
    def search(q: str = Query("", alias="q"), limit: int = Query(100)) -> dict[str, Any]:
        news = db_search_news(q, limit=limit) if q else []
        return {"keyword": q, "count": len(news), "news": [item.to_dict() for item in news]}

    @router.get("/api/detail")
    def detail(id: int = Query(0)) -> dict[str, Any]:
        news = db_get_news_by_id(id)
        if not news:
            return {"success": False, "error": "News not found"}
        db_mark_read(id, True)
        return {"success": True, "news": news.to_dict()}

    @router.post("/api/favorite", response_model=None)
    def favorite(data: dict[str, Any] = Body(default={})) -> Any:
        try:
            news_id = int(data.get("id", 0))
            if news_id <= 0:
                return response({"success": False, "error": "Invalid id"}, status=400)
            return {"success": True, "is_favorite": service.set_favorite(news_id, db_toggle_favorite)}
        except Exception as exc:  # noqa: BLE001
            return response({"success": False, "error": str(exc)}, status=500)

    @router.post("/api/read", response_model=None)
    def read(data: dict[str, Any] = Body(default={})) -> Any:
        try:
            news_id = int(data.get("id", 0))
            if news_id <= 0:
                return response({"success": False, "error": "Invalid id"}, status=400)
            service.mark_read(news_id, bool(data.get("read", True)), db_mark_read)
            return {"success": True}
        except Exception as exc:  # noqa: BLE001
            return response({"success": False, "error": str(exc)}, status=500)

    return router
