"""Migrate legacy ``components`` documents into typed ``cmdb_*`` collections."""

from __future__ import annotations

from typing import Any

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from ..models.components import ComponentType
from ..tenancy import MIGRATION_TENANT_ID, MISSING_TENANT_ID_FILTER, require_tenant_id
from .cmdb_collections import (
    LEGACY_COMPONENTS_COLLECTION,
    TYPED_CMDB_COLLECTIONS,
    collection_name_for_type,
    ensure_typed_cmdb_indexes,
)


def _copy_doc(raw: dict[str, Any]) -> dict[str, Any]:
    """Shallow copy without Mongo ``_id`` so upserts can re-insert cleanly."""
    return {k: v for k, v in raw.items() if k != "_id"}


def migrate_components_to_typed(
    db: Database,
    *,
    default_tenant_id: str = MIGRATION_TENANT_ID,
    remove_legacy: bool = False,
) -> dict[str, Any]:
    """Idempotently copy ``components`` → typed ``cmdb_*`` collections.

    - Stamps missing ``tenant_id`` with ``default_tenant_id`` on the copy.
    - Skips rows whose ``component_id`` already exists in the target typed
      collection (idempotent re-runs).
    - Leaves legacy ``components`` in place unless ``remove_legacy=True``.
    """
    ensure_typed_cmdb_indexes(db)
    tid_default = require_tenant_id(default_tenant_id)
    legacy = db[LEGACY_COMPONENTS_COLLECTION]

    stats: dict[str, Any] = {
        "ok": True,
        "scanned": 0,
        "migrated": 0,
        "skipped_existing": 0,
        "skipped_invalid_type": 0,
        "errors": [],
        "by_collection": {name: 0 for name in TYPED_CMDB_COLLECTIONS},
        "removed_legacy": 0,
        "default_tenant_id": tid_default,
        "remove_legacy": remove_legacy,
    }

    for raw in legacy.find({}):
        stats["scanned"] += 1
        doc = _copy_doc(raw)
        ctype_raw = doc.get("component_type")
        try:
            ctype = ComponentType(str(ctype_raw))
        except ValueError:
            stats["skipped_invalid_type"] += 1
            stats["errors"].append(
                {
                    "component_id": doc.get("component_id"),
                    "error": f"invalid component_type={ctype_raw!r}",
                }
            )
            continue

        if not doc.get("tenant_id"):
            doc["tenant_id"] = tid_default

        target_name = collection_name_for_type(ctype)
        target = db[target_name]
        cid = doc.get("component_id")
        if not cid:
            stats["skipped_invalid_type"] += 1
            stats["errors"].append({"component_id": None, "error": "missing component_id"})
            continue

        existing = target.find_one({"component_id": cid}, {"_id": 1})
        if existing is not None:
            stats["skipped_existing"] += 1
            continue

        try:
            target.insert_one(doc)
            stats["migrated"] += 1
            stats["by_collection"][target_name] += 1
        except DuplicateKeyError:
            stats["skipped_existing"] += 1
        except Exception as exc:  # noqa: BLE001 — report and continue
            stats["ok"] = False
            stats["errors"].append({"component_id": cid, "error": str(exc)})

    if remove_legacy and stats["ok"] and not stats["errors"]:
        # Only wipe legacy when every scanned row was migrated or already present.
        result = legacy.delete_many({})
        stats["removed_legacy"] = int(result.deleted_count)

    stats["typed_collections"] = list(TYPED_CMDB_COLLECTIONS)
    stats["legacy_collection"] = LEGACY_COMPONENTS_COLLECTION
    return stats


def backfill_typed_null_tenant_ids(
    db: Database, *, tenant_id: str = MIGRATION_TENANT_ID
) -> dict[str, int]:
    """Backfill null/missing tenant_id on typed CMDB collections only."""
    tid = require_tenant_id(tenant_id)
    modified: dict[str, int] = {}
    for name in TYPED_CMDB_COLLECTIONS:
        result = db[name].update_many(
            MISSING_TENANT_ID_FILTER,
            {"$set": {"tenant_id": tid}},
        )
        modified[name] = int(result.modified_count)
    return modified
