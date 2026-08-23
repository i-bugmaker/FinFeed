"""Operational endpoints that do not belong to a financial domain."""

from fastapi import APIRouter


def create_router(version: str) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/api/ping")
    def ping() -> dict[str, str]:
        return {"service": "FinFeed API", "version": version, "docs": "/docs"}

    return router
