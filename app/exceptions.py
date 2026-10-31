"""Centralized exception handlers for FastAPI."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .db import DatabaseUnavailableError

logger = logging.getLogger(__name__)


def _error_body(
    *,
    code: str,
    message: str,
    details: Any = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body


def _json_safe(value: Any) -> Any:
    """Make Pydantic/FastAPI error payloads JSON-serializable."""
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, BaseException):
        return str(value)
    try:
        import json

        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach centralized exception handlers to the FastAPI app."""

    @app.exception_handler(DatabaseUnavailableError)
    async def database_unavailable_handler(
        request: Request, exc: DatabaseUnavailableError
    ) -> JSONResponse:
        logger.error(
            "database_unavailable path=%s detail=%s",
            request.url.path,
            exc.message,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_error_body(
                code="database_unavailable",
                message="MongoDB is currently unavailable",
                details=exc.message,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        detail = exc.detail
        message = detail if isinstance(detail, str) else "HTTP error"
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(code="http_error", message=message, details=detail),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = _json_safe(exc.errors())
        logger.info("validation_error path=%s errors=%s", request.url.path, details)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_body(
                code="validation_error",
                message="Request validation failed",
                details=details,
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception path=%s", request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(
                code="internal_error",
                message="An unexpected error occurred",
            ),
        )
