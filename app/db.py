"""MongoDB access via PyMongo with graceful connection-error handling."""

from __future__ import annotations

import logging
from typing import Any

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, PyMongoError, ServerSelectionTimeoutError

from .config import Settings, get_settings
from .serialization import serialize_document

logger = logging.getLogger(__name__)

_client: MongoClient | None = None


class DatabaseUnavailableError(Exception):
    """Raised when MongoDB cannot be reached or selected."""

    def __init__(self, message: str = "MongoDB is unavailable") -> None:
        super().__init__(message)
        self.message = message


def get_client(settings: Settings | None = None) -> MongoClient:
    """Return a process-wide MongoClient (lazy)."""
    global _client
    if _client is not None:
        return _client

    cfg = settings or get_settings()
    _client = MongoClient(
        cfg.mongodb_uri,
        connectTimeoutMS=cfg.mongodb_connect_timeout_ms,
        serverSelectionTimeoutMS=cfg.mongodb_server_selection_timeout_ms,
        connect=False,
    )
    return _client


def get_database(settings: Settings | None = None) -> Database:
    """Return the configured database handle (does not force a network round-trip)."""
    cfg = settings or get_settings()
    return get_client(cfg)[cfg.mongodb_db]


def ping_database(settings: Settings | None = None) -> dict[str, Any]:
    """Ping MongoDB and return a status payload.

    Never raises for connectivity problems — returns structured status instead.
    """
    cfg = settings or get_settings()
    try:
        client = get_client(cfg)
        result = client.admin.command("ping")
        return {
            "ok": True,
            "database": cfg.mongodb_db,
            "ping": serialize_document(dict(result)) if isinstance(result, dict) else result,
        }
    except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
        logger.warning("mongodb_ping_failed error=%s", exc)
        return {
            "ok": False,
            "database": cfg.mongodb_db,
            "error": "connection_failed",
            "detail": str(exc),
        }
    except PyMongoError as exc:
        logger.warning("mongodb_ping_error error=%s", exc)
        return {
            "ok": False,
            "database": cfg.mongodb_db,
            "error": "mongodb_error",
            "detail": str(exc),
        }


def require_database(settings: Settings | None = None) -> Database:
    """Return database after verifying connectivity; raise if unavailable."""
    status = ping_database(settings)
    if not status.get("ok"):
        raise DatabaseUnavailableError(status.get("detail") or "MongoDB is unavailable")
    return get_database(settings)


def close_client() -> None:
    """Close and clear the shared MongoClient."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def reset_client_for_tests() -> None:
    """Test helper: drop cached client so settings can be reapplied."""
    close_client()
