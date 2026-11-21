"""Idempotent indexes for Monitoring collections (monitor DB only)."""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING
from pymongo.database import Database

from ...db import require_monitor_database
from .. import MONITOR_COLLECTIONS

FILE_TARGETS_COLLECTION = "file_watch_targets"
FILE_EVENTS_COLLECTION = "file_version_events"
MONITOR_TARGETS_COLLECTION = "monitor_targets"
METRIC_SAMPLES_COLLECTION = "metric_samples"


def ensure_monitor_indexes(db: Database | None = None) -> dict[str, Any]:
    """Create Monitoring collection indexes. Safe to call repeatedly."""
    handle = db if db is not None else require_monitor_database()
    created: dict[str, list[str]] = {}

    file_targets = handle[FILE_TARGETS_COLLECTION]
    created[FILE_TARGETS_COLLECTION] = [
        str(
            file_targets.create_index(
                [("tenant_id", ASCENDING), ("watch_id", ASCENDING)],
                unique=True,
                name="tenant_watch_id_unique",
            )
        ),
        str(
            file_targets.create_index(
                [("tenant_id", ASCENDING), ("path", ASCENDING)],
                name="tenant_path_idx",
            )
        ),
        str(
            file_targets.create_index(
                [("tenant_id", ASCENDING)], name="tenant_id_idx"
            )
        ),
    ]

    file_events = handle[FILE_EVENTS_COLLECTION]
    created[FILE_EVENTS_COLLECTION] = [
        str(
            file_events.create_index(
                [("tenant_id", ASCENDING), ("event_id", ASCENDING)],
                unique=True,
                name="tenant_event_id_unique",
            )
        ),
        str(
            file_events.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("watch_id", ASCENDING),
                    ("version", ASCENDING),
                ],
                name="tenant_watch_version_idx",
            )
        ),
        str(
            file_events.create_index(
                [("tenant_id", ASCENDING), ("changed_at", ASCENDING)],
                name="tenant_changed_at_idx",
            )
        ),
        str(
            file_events.create_index(
                [("tenant_id", ASCENDING)], name="tenant_id_idx"
            )
        ),
    ]

    monitor_targets = handle[MONITOR_TARGETS_COLLECTION]
    created[MONITOR_TARGETS_COLLECTION] = [
        str(
            monitor_targets.create_index(
                [("tenant_id", ASCENDING), ("target_id", ASCENDING)],
                unique=True,
                name="tenant_target_id_unique",
            )
        ),
        str(
            monitor_targets.create_index(
                [("tenant_id", ASCENDING), ("component_id", ASCENDING)],
                unique=True,
                name="tenant_component_id_unique",
            )
        ),
        str(
            monitor_targets.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("domain", ASCENDING),
                    ("status", ASCENDING),
                ],
                name="tenant_domain_status_idx",
            )
        ),
        str(
            monitor_targets.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("collect_mode", ASCENDING),
                    ("target_kind", ASCENDING),
                ],
                name="tenant_collect_kind_idx",
            )
        ),
        str(
            monitor_targets.create_index(
                [("tenant_id", ASCENDING), ("os_family", ASCENDING)],
                name="tenant_os_family_idx",
            )
        ),
    ]

    samples = handle[METRIC_SAMPLES_COLLECTION]
    created[METRIC_SAMPLES_COLLECTION] = [
        str(
            samples.create_index(
                [("tenant_id", ASCENDING), ("sample_id", ASCENDING)],
                unique=True,
                name="tenant_sample_id_unique",
            )
        ),
        str(
            samples.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("target_id", ASCENDING),
                    ("observed_at", ASCENDING),
                ],
                name="tenant_target_observed_idx",
            )
        ),
        str(
            samples.create_index(
                [
                    ("tenant_id", ASCENDING),
                    ("component_id", ASCENDING),
                    ("metric_name", ASCENDING),
                ],
                name="tenant_component_metric_idx",
            )
        ),
    ]

    return {"ok": True, "indexes": created, "collections": list(MONITOR_COLLECTIONS)}
