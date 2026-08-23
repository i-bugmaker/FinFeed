"""Transport boundary for market-data endpoints."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request


def create_router(dispatch: Callable[[str, Request], Awaitable[Any]]) -> APIRouter:
    """Expose the stable market URL while allowing domain dispatch replacement."""
    router = APIRouter(tags=["market"])

    @router.api_route("/api/market/{rest:path}", methods=["GET", "POST"], response_model=None)
    async def market(rest: str, request: Request) -> Any:
        return await dispatch(rest, request)

    return router
