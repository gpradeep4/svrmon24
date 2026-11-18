"""Idempotent indexes for ITSM collections (ITSM DB only)."""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

from ...db import require_itsm_database
from .. import ITSM_COLLECTIONS

INCIDENTS = "itsm_incidents"
CHANGES = "itsm_changes"
PROBLEMS = "itsm_problems"
ACTIVITIES = "itsm_ticket_activities"
COUNTERS = "itsm_counters"


def _ticket_indexes(coll, *, id_field: str, prefix: str) -> list[str]:
    names = [
        coll.create_index(
            [("tenant_id", ASCENDING), (id_field, ASCENDING)],
            unique=True,
            name=f"tenant_{prefix}_id_unique",
        ),
        coll.create_index(
            [("tenant_id", ASCENDING), ("number", ASCENDING)],
            unique=True,
            name=f"tenant_{prefix}_number_unique",
        ),
        coll.create_index(
            [("tenant_id", ASCENDING), ("status", ASCENDING), ("updated_at", DESCENDING)],
            name=f"tenant_{prefix}_status_updated_idx",
        ),
        coll.create_index(
            [
                ("tenant_id", ASCENDING),
                ("assignee_user_id", ASCENDING),
                ("status", ASCENDING),
            ],
            name=f"tenant_{prefix}_assignee_status_idx",
        ),
        coll.create_index(
            [("tenant_id", ASCENDING), ("ci_links.component_id", ASCENDING)],
            name=f"tenant_{prefix}_ci_component_idx",
        ),
        coll.create_index([("tenant_id", ASCENDING)], name=f"tenant_{prefix}_tenant_id_idx"),
    ]
    return [str(n) for n in names]


def ensure_itsm_indexes(db: Database | None = None) -> dict[str, Any]:
    """Create ITSM collection indexes. Safe to call repeatedly."""
    handle = db if db is not None else require_itsm_database()
    created: dict[str, list[str]] = {}

    created[INCIDENTS] = _ticket_indexes(
        handle[INCIDENTS], id_field="incident_id", prefix="incident"
    )
    created[CHANGES] = _ticket_indexes(
        handle[CHANGES], id_field="change_id", prefix="change"
    )
    created[PROBLEMS] = _ticket_indexes(
        handle[PROBLEMS], id_field="problem_id", prefix="problem"
    )

    act = handle[ACTIVITIES]
    names = [
        act.create_index(
            [("tenant_id", ASCENDING), ("activity_id", ASCENDING)],
            unique=True,
            name="tenant_activity_id_unique",
        ),
        act.create_index(
            [
                ("tenant_id", ASCENDING),
                ("ticket_type", ASCENDING),
                ("ticket_id", ASCENDING),
                ("created_at", DESCENDING),
            ],
            name="tenant_ticket_created_idx",
        ),
        act.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx"),
    ]
    created[ACTIVITIES] = [str(n) for n in names]

    ctr = handle[COUNTERS]
    names = [
        ctr.create_index(
            [("tenant_id", ASCENDING), ("counter_key", ASCENDING)],
            unique=True,
            name="tenant_counter_key_unique",
        ),
    ]
    created[COUNTERS] = [str(n) for n in names]

    return {
        "ok": True,
        "database": handle.name,
        "collections": list(ITSM_COLLECTIONS),
        "indexes": created,
    }
