"""Idempotent indexes for Monitoring collections (monitor DB only)."""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING
from pymongo.database import Database

from ...db import require_monitor_database
from .. import MONITOR_COLLECTIONS

TARGETS_COLLECTION = "file_watch_targets"
EVENTS_COLLECTION = "file_version_events"


def ensure_monitor_indexes(db: Database | None = None) -> dict[str, Any]:
    """Create Monitoring collection indexes. Safe to call repeatedly."""
    handle = db if db is not None else require_monitor_database()
    created: dict[str, list[str]] = {}

    targets = handle[TARGETS_COLLECTION]
    created[TARGETS_COLLECTION] = [
        str(
            targets.create_index(
                [("tenant_id", ASCENDING), ("watch_id", ASCENDING)],
                unique=True,
                name="tenant_watch_id_unique",
            )
        ),
        str(
            targets.create_index(
                [("tenant_id", ASCENDING), ("path", ASCENDING)],
                name="tenant_path_idx",
            )
        ),
        str(targets.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")),
    ]

    events = handle[EVENTS_COLLECTION]
    created[EVENTS_COLLECTION] = [
        str(
            events.create_index(
                [("tenant_id", ASCENDING), ("event_id", ASCENDING)],
                unique=True,
                name="tenant_event_id_unique",
            )
        ),
        str(
            events.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("watch_id", ASCENDING),
                    ("version", ASCENDING),
                ],
                name="tenant_watch_version_idx",
            )
        ),
        str(
            events.create_index(
                [("tenant_id", ASCENDING), ("changed_at", ASCENDING)],
                name="tenant_changed_at_idx",
            )
        ),
        str(events.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")),
    ]

    return {"ok": True, "indexes": created, "collections": list(MONITOR_COLLECTIONS)}
