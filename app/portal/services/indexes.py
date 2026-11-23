"""Idempotent indexes for Service Portal collections (ITSM DB)."""

from __future__ import annotations

from pymongo import ASCENDING
from pymongo.database import Database

from ...db import require_itsm_database

CATALOG_ITEMS = "sp_catalog_items"
REQUESTS = "sp_requests"
EXECUTION_RUNS = "sp_execution_runs"
AUDIT_EVENTS = "sp_audit_events"

_ensured = False


def ensure_portal_indexes(db: Database | None = None) -> list[str]:
    """Create portal indexes on the ITSM database (idempotent)."""
    global _ensured
    database = db or require_itsm_database()
    names: list[str] = []
    catalog = database[CATALOG_ITEMS]
    names.append(
        catalog.create_index(
            [("tenant_id", ASCENDING), ("item_id", ASCENDING)],
            unique=True,
            name="tenant_sp_item_id_unique",
        )
    )
    names.append(
        catalog.create_index(
            [("tenant_id", ASCENDING), ("key", ASCENDING)],
            unique=True,
            name="tenant_sp_item_key_unique",
        )
    )
    names.append(
        catalog.create_index(
            [("tenant_id", ASCENDING), ("domain", ASCENDING), ("enabled", ASCENDING)],
            name="tenant_sp_item_domain_enabled_idx",
        )
    )
    requests = database[REQUESTS]
    names.append(
        requests.create_index(
            [("tenant_id", ASCENDING), ("request_id", ASCENDING)],
            unique=True,
            name="tenant_sp_request_id_unique",
        )
    )
    names.append(
        requests.create_index(
            [("tenant_id", ASCENDING), ("change_id", ASCENDING)],
            name="tenant_sp_request_change_idx",
        )
    )
    names.append(
        requests.create_index(
            [("tenant_id", ASCENDING), ("status", ASCENDING), ("updated_at", ASCENDING)],
            name="tenant_sp_request_status_updated_idx",
        )
    )
    runs = database[EXECUTION_RUNS]
    names.append(
        runs.create_index(
            [("tenant_id", ASCENDING), ("run_id", ASCENDING)],
            unique=True,
            name="tenant_sp_run_id_unique",
        )
    )
    names.append(
        runs.create_index(
            [("tenant_id", ASCENDING), ("request_id", ASCENDING)],
            name="tenant_sp_run_request_idx",
        )
    )
    audit = database[AUDIT_EVENTS]
    names.append(
        audit.create_index(
            [("tenant_id", ASCENDING), ("event_id", ASCENDING)],
            unique=True,
            name="tenant_sp_audit_id_unique",
        )
    )
    _ensured = True
    return names
