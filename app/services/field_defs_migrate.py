"""Migrate legacy ``custom_field_definitions`` → ``cmdb_field_definitions``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from ..models.custom_fields import BUILTIN_FIELD_KEYS, FieldOrigin, FieldStorage
from ..tenancy import MIGRATION_TENANT_ID, require_tenant_id
from .custom_fields import (
    COLLECTION,
    LEGACY_COLLECTION,
    ensure_builtin_definitions,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _copy_doc(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in raw.items() if k != "_id"}


def migrate_custom_fields_to_cmdb(
    db: Database,
    *,
    default_tenant_id: str = MIGRATION_TENANT_ID,
    remove_legacy: bool = False,
    seed_builtins_for_tenants: list[str] | None = None,
) -> dict[str, Any]:
    """Idempotently copy legacy custom field defs → ``cmdb_field_definitions``.

    - Stamps missing ``tenant_id`` with ``default_tenant_id``.
    - Adds Phase 7 shape (``origin=custom``, ``storage=custom_fields``, …).
    - Skips rows whose ``(tenant_id, field_key)`` already exists in the target.
    - Seeds locked OS/product built-ins for the migration tenant (+ any listed).
    - Leaves legacy collection unless ``remove_legacy=True``.
    """
    tid_default = require_tenant_id(default_tenant_id)
    legacy = db[LEGACY_COLLECTION]
    target = db[COLLECTION]

    # Ensure unique (tenant_id, field_key) on the new collection.
    target.create_index(
        [("tenant_id", 1), ("field_key", 1)],
        unique=True,
        name="tenant_field_key_unique",
    )
    target.create_index([("tenant_id", 1)], name="tenant_id_idx")

    stats: dict[str, Any] = {
        "ok": True,
        "scanned": 0,
        "migrated": 0,
        "skipped_existing": 0,
        "skipped_invalid": 0,
        "errors": [],
        "removed_legacy": 0,
        "default_tenant_id": tid_default,
        "remove_legacy": remove_legacy,
        "builtins": {},
        "target_collection": COLLECTION,
        "legacy_collection": LEGACY_COLLECTION,
    }

    tenants_seen: set[str] = {tid_default}
    now = _now()

    for raw in legacy.find({}):
        stats["scanned"] += 1
        doc = _copy_doc(raw)
        field_key = doc.get("field_key")
        if not field_key or not isinstance(field_key, str):
            stats["skipped_invalid"] += 1
            stats["errors"].append({"field_key": field_key, "error": "missing field_key"})
            continue

        tid = (doc.get("tenant_id") or "").strip() or tid_default
        doc["tenant_id"] = tid
        tenants_seen.add(tid)

        # Do not migrate reserved keys as custom — builtins are seeded separately.
        if field_key in BUILTIN_FIELD_KEYS:
            stats["skipped_invalid"] += 1
            stats["errors"].append(
                {
                    "field_key": field_key,
                    "tenant_id": tid,
                    "error": "reserved builtin key skipped from legacy custom migrate",
                }
            )
            continue

        existing = target.find_one({"tenant_id": tid, "field_key": field_key}, {"_id": 1})
        if existing is not None:
            stats["skipped_existing"] += 1
            continue

        doc.setdefault("label", field_key)
        doc.setdefault("field_type", "string")
        doc.setdefault("applies_to", ["*"])
        doc.setdefault("required", False)
        doc.setdefault("enum_values", [])
        doc["origin"] = FieldOrigin.CUSTOM.value
        doc["storage"] = FieldStorage.CUSTOM_FIELDS.value
        doc.setdefault("description", None)
        doc.setdefault("active", True)
        doc["locked"] = False
        doc.setdefault("created_at", now)
        doc["updated_at"] = now

        try:
            target.insert_one(doc)
            stats["migrated"] += 1
        except DuplicateKeyError:
            stats["skipped_existing"] += 1
        except Exception as exc:  # noqa: BLE001
            stats["ok"] = False
            stats["errors"].append(
                {"field_key": field_key, "tenant_id": tid, "error": str(exc)}
            )

    if seed_builtins_for_tenants is None:
        seed_list = sorted(tenants_seen)
    else:
        seed_list = sorted({require_tenant_id(t) for t in seed_builtins_for_tenants})

    for tid in seed_list:
        stats["builtins"][tid] = ensure_builtin_definitions(tenant_id=tid)

    if remove_legacy and stats["ok"]:
        result = legacy.delete_many({})
        stats["removed_legacy"] = int(result.deleted_count)

    return stats
