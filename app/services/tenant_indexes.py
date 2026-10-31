"""Index planning for shared-DB tenancy (Master Phase 4).

Phase 4 adds non-unique ``tenant_id`` indexes on CMDB collections while keeping
global unique keys (notably ``component_id``). Phase 5 will:

1. Backfill null ``tenant_id`` → ``tenant-svrmon24-legacy``
2. Make ``tenant_id`` mandatory on writes
3. Add compound unique indexes where appropriate (except ``component_id``, which
   remains **globally** unique per preferences)
4. Enforce ``tenant_id`` filters on every read/write/aggregate
"""

from __future__ import annotations

from pymongo import ASCENDING
from pymongo.database import Database

from ..tenancy import TENANTED_COLLECTIONS


def ensure_tenant_id_indexes(db: Database) -> dict[str, list[str]]:
    """Create Phase-4 ``tenant_id`` indexes on tenanted collections.

    Does **not** change uniqueness of ``component_id`` / ``field_key`` /
    ``relationship_id`` / ``diagnostic_id`` — those stay global for now.
    """
    created: dict[str, list[str]] = {}
    for name in TENANTED_COLLECTIONS:
        coll = db[name]
        # Non-unique tenant_id for Phase 5 scoping prep.
        coll.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")
        names = ["tenant_id_idx"]
        # Helpful compounds for future scoped lists (still non-unique).
        if name == "components":
            coll.create_index(
                [("tenant_id", ASCENDING), ("component_type", ASCENDING)],
                name="tenant_component_type_idx",
            )
            coll.create_index(
                [("tenant_id", ASCENDING), ("environment", ASCENDING)],
                name="tenant_environment_idx",
            )
            names.extend(["tenant_component_type_idx", "tenant_environment_idx"])
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
            names.extend(["tenant_rel_source_idx", "tenant_rel_target_idx"])
        elif name == "diagnostic_history":
            coll.create_index(
                [("tenant_id", ASCENDING), ("timestamp", ASCENDING)],
                name="tenant_diag_timestamp_idx",
            )
            names.append("tenant_diag_timestamp_idx")
        created[name] = names
    return created


PHASE5_MIGRATION_NOTES = """
Phase 5 migration path (not executed in Phase 4):

1. ensure_migration_tenant()  # already Phase 4
2. For each of components, custom_field_definitions, cmdb_relationships,
   diagnostic_history:
     db.<coll>.update_many(
       {"$or": [{"tenant_id": {"$exists": false}}, {"tenant_id": None}, {"tenant_id": ""}]},
       {"$set": {"tenant_id": "tenant-svrmon24-legacy"}},
     )
3. Keep unique index on component_id (GLOBAL — preference).
4. Consider unique (tenant_id, field_key) replacing global field_key unique when
   multi-org is enabled; same for relationship duplicate_key if needed.
5. Wrap every service query with {"tenant_id": <auth.tenant_id>}.
6. Add cross-tenant denial tests; then enable org switcher only after isolation.
"""
