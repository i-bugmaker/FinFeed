"""Transport-level error contracts and exception handlers."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("news_monitor")


@dataclass(frozen=True)
class ErrorBody:
    """Stable JSON error payload shared by all new API endpoints."""

    code: str
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        return {key: value for key, value in body.items() if value is not None}


class ApiError(Exception):
    """Known client-facing failure raised by transport adapters."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        code: str = "BAD_REQUEST",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = ErrorBody(code=code, message=message, details=details)


def error_response(status_code: int, code: str, message: str, **details: Any) -> JSONResponse:
    """Create the canonical error response without leaking framework details."""
    body = ErrorBody(code=code, message=message, details=details or None)
    return JSONResponse(status_code=status_code, content={"success": False, "error": body.to_dict()})


def install_exception_handlers(app: FastAPI) -> None:
    """Install one error policy at the application boundary.

    Legacy endpoints retain their existing response payloads. New routers can
    raise :class:`ApiError`; unexpected faults receive a safe, structured 500.
    """

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "error": exc.body.to_dict()},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error for %s", request.url.path, exc_info=exc)
        return error_response(500, "INTERNAL_ERROR", "服务暂时不可用，请稍后重试")
