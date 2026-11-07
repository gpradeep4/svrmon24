"""Index planning for shared-DB tenancy (Master Phase 5–8).

Phase 5:

1. Backfill null ``tenant_id`` → ``tenant-svrmon24-legacy``
2. Make ``tenant_id`` mandatory on writes
3. Enforce ``tenant_id`` filters on every read/write/aggregate
4. Keep compound indexes with ``tenant_id`` for scoped lists
5. Keep ``component_id`` **globally** unique (preference)

Phase 6:

6. Typed ``cmdb_*`` collections get the same tenant compound indexes
7. Legacy ``components`` indexes retained for migration / fallback

Phase 7:

8. ``cmdb_field_definitions`` unique ``(tenant_id, field_key)``
9. Legacy ``custom_field_definitions`` indexes retained for migration

Phase 8:

10. ``cmdb_column_configurations`` unique ``(tenant_id, grid_key)``
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
    TYPED_CMDB_COLLECTIONS,
)
from .cmdb_collections import ensure_typed_cmdb_indexes


def ensure_tenant_id_indexes(db: Database) -> dict[str, list[str]]:
    """Create tenant_id (+ compound) indexes on tenanted collections.

    Does **not** change uniqueness of ``component_id`` — it stays globally unique
    (per typed collection unique index + service-layer cross-collection checks).
    """
    created: dict[str, list[str]] = {}
    created.update(ensure_typed_cmdb_indexes(db))

    for name in TENANTED_COLLECTIONS:
        if name in TYPED_CMDB_COLLECTIONS:
            continue  # already indexed above
        coll = db[name]
        coll.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")
        names = ["tenant_id_idx"]
        if name == "components":
            coll.create_index([("component_id", ASCENDING)], unique=True)
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
                    "component_id_1",
                    "tenant_component_type_idx",
                    "tenant_environment_idx",
                    "tenant_status_idx",
                ]
            )
        elif name == "cmdb_field_definitions":
            coll.create_index(
                [("tenant_id", ASCENDING), ("field_key", ASCENDING)],
                unique=True,
                name="tenant_field_key_unique",
            )
            coll.create_index(
                [("tenant_id", ASCENDING), ("origin", ASCENDING)],
                name="tenant_origin_idx",
            )
            names.extend(["tenant_field_key_unique", "tenant_origin_idx"])
        elif name == "cmdb_column_configurations":
            coll.create_index(
                [("tenant_id", ASCENDING), ("grid_key", ASCENDING)],
                unique=True,
                name="tenant_grid_key_unique",
            )
            names.append("tenant_grid_key_unique")
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

PHASE6_MIGRATION_NOTES = """
Phase 6 migration (typed CMDB):

1. ensure_typed_cmdb_indexes() on cmdb_servers/network/middleware/databases/applications
2. migrate_components_to_typed() copies legacy components → typed collections
3. Service layer writes/reads typed collections; /api/components* facade unchanged
4. Legacy components retained as migration source / read fallback (unless --remove-legacy)
5. tenant_id still mandatory; component_id still globally unique across types
"""

PHASE7_MIGRATION_NOTES = """
Phase 7 migration (field definitions):

1. migrate_custom_fields_to_cmdb() copies custom_field_definitions → cmdb_field_definitions
2. Unique index (tenant_id, field_key) on cmdb_field_definitions
3. Seed locked built-in OS Family/OS Version + Product Type/Product Version (native storage)
4. /api/custom-fields remains a facade; /api/field-definitions is canonical
5. Custom values still attach on component custom_fields; column configs are Phase 8
"""

PHASE8_MIGRATION_NOTES = """
Phase 8 (column configurations):

1. cmdb_column_configurations unique (tenant_id, grid_key)
2. Defaults for inventory + relationships grids (no legacy migrate)
3. Locked columns stay visible: OS Family/Version, Product Type/Version,
   protocol, source_port, target_port (+ actions)
4. /api/column-configurations drives Column Settings UI + grid rendering
"""
