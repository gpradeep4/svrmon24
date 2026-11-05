"""Index planning for shared-DB tenancy (Master Phase 5 — hard isolation).

Phase 5:

1. Backfill null ``tenant_id`` → ``tenant-svrmon24-legacy``
2. Make ``tenant_id`` mandatory on writes
3. Enforce ``tenant_id`` filters on every read/write/aggregate
4. Keep compound indexes with ``tenant_id`` for scoped lists
5. Keep ``component_id`` **globally** unique (preference)
"""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING
from pymongo.database import Database

from ..tenancy import (
    ISOLATION_ENFORCED,
    MIGRATION_TENANT_ID,
    MISSING_TENANT_ID_FILTER,
    TENANTED_COLLECTIONS,
)


def ensure_tenant_id_indexes(db: Database) -> dict[str, list[str]]:
    """Create tenant_id (+ compound) indexes on tenanted collections.

    Does **not** change uniqueness of ``component_id`` — it stays globally unique.
    """
    created: dict[str, list[str]] = {}
    for name in TENANTED_COLLECTIONS:
        coll = db[name]
        coll.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")
        names = ["tenant_id_idx"]
        if name == "components":
            coll.create_index(
                [("tenant_id", ASCENDING), ("component_type", ASCENDING)],
                name="tenant_component_type_idx",
            )
            coll.create_index(
                [("tenant_id", ASCENDING), ("environment", ASCENDING)],
                name="tenant_environment_idx",
            )
            coll.create_index(
                [("tenant_id", ASCENDING), ("status", ASCENDING)],
                name="tenant_status_idx",
            )
            names.extend(
                [
                    "tenant_component_type_idx",
                    "tenant_environment_idx",
                    "tenant_status_idx",
                ]
            )
        elif name == "custom_field_definitions":
            coll.create_index(
                [("tenant_id", ASCENDING), ("field_key", ASCENDING)],
                name="tenant_field_key_idx",
            )
            names.append("tenant_field_key_idx")
        elif name == "cmdb_relationships":
            coll.create_index(
                [("tenant_id", ASCENDING), ("source_component_id", ASCENDING)],
                name="tenant_rel_source_idx",
            )
            coll.create_index(
                [("tenant_id", ASCENDING), ("target_component_id", ASCENDING)],
                name="tenant_rel_target_idx",
            )
            coll.create_index(
                [("tenant_id", ASCENDING), ("duplicate_key", ASCENDING)],
                name="tenant_rel_duplicate_idx",
            )
            names.extend(
                [
                    "tenant_rel_source_idx",
                    "tenant_rel_target_idx",
                    "tenant_rel_duplicate_idx",
                ]
            )
        elif name == "diagnostic_history":
            coll.create_index(
                [("tenant_id", ASCENDING), ("timestamp", ASCENDING)],
                name="tenant_diag_timestamp_idx",
            )
            coll.create_index(
                [("tenant_id", ASCENDING), ("component_id", ASCENDING)],
                name="tenant_diag_component_idx",
            )
            names.extend(["tenant_diag_timestamp_idx", "tenant_diag_component_idx"])
        created[name] = names
    return created


def backfill_null_tenant_ids(
    db: Database,
    *,
    tenant_id: str = MIGRATION_TENANT_ID,
) -> dict[str, Any]:
    """Set missing/null/empty ``tenant_id`` to the migration tenant (idempotent)."""
    results: dict[str, int] = {}
    for name in TENANTED_COLLECTIONS:
        result = db[name].update_many(
            MISSING_TENANT_ID_FILTER,
            {"$set": {"tenant_id": tenant_id}},
        )
        results[name] = int(result.modified_count)
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "modified": results,
        "isolation_enforced": ISOLATION_ENFORCED,
    }


PHASE5_MIGRATION_NOTES = """
Phase 5 migration (executed):

1. ensure_migration_tenant()
2. backfill_null_tenant_ids() → tenant-svrmon24-legacy
3. Require tenant_id on all CMDB writes (stamp_tenant_id)
4. Scope every query/aggregate with {"tenant_id": <current>}
5. Keep unique index on component_id (GLOBAL)
6. Cross-tenant denial returns 404; Basic auth still scoped to migration tenant
7. Org switcher remains disabled until multi-org UX is intentionally enabled
"""
