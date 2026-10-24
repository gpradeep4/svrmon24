"""Structured logging setup."""

from __future__ import annotations

import logging
import sys
from typing import Any

_SKIP_KEYS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Minimal structured log formatter (key=value for readability)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _SKIP_KEYS
        }
        if extras:
            payload["extra"] = extras
        parts = [f"{key}={value!r}" for key, value in payload.items()]
        return " ".join(parts)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logger once for the process."""
    root = logging.getLogger()
    if getattr(root, "_svrmon24_configured", False):
        root.setLevel(level.upper())
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    setattr(root, "_svrmon24_configured", True)

    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
