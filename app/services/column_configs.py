"""CMDB column-configuration persistence (tenant-scoped, Master Phase 8).

Collection: ``cmdb_column_configurations`` — one document per ``(tenant_id, grid_key)``.

Inventory catalogs merge active custom field definitions so new fields appear as
toggleable columns (visible by default) without collapsing locked OS/product keys.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection

from ..db import require_database
from ..models.column_configs import (
    GRID_KEYS,
    ColumnConfigurationUpdate,
    GridKey,
    default_columns_for_grid,
    locked_columns_for_grid,
    merge_inventory_custom_field_columns,
)
from ..models.custom_fields import FieldOrigin
from ..serialization import serialize_document
from ..tenancy import require_tenant_id, stamp_tenant_id, tenant_filter
from . import custom_fields as custom_fields_service

COLLECTION = "cmdb_column_configurations"


class ColumnConfigError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _collection() -> Collection:
    coll = require_database()[COLLECTION]
    coll.create_index(
        [("tenant_id", ASCENDING), ("grid_key", ASCENDING)],
        unique=True,
        name="tenant_grid_key_unique",
    )
    coll.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")
    return coll


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _custom_field_definitions(*, tenant_id: str) -> list[dict[str, Any]]:
    """Active custom (non-builtin) field defs for Inventory column catalog."""
    return custom_fields_service.list_definitions(
        tenant_id=tenant_id,
        origin=FieldOrigin.CUSTOM.value,
        include_inactive=False,
    )


def catalog_columns_for_grid(grid_key: str, *, tenant_id: str) -> list[dict[str, Any]]:
    """Full column catalog for a grid (Inventory includes custom fields)."""
    key = validate_grid_key(grid_key)
    if key == GridKey.INVENTORY.value:
        return merge_inventory_custom_field_columns(
            default_columns_for_grid(key),
            _custom_field_definitions(tenant_id=tenant_id),
        )
    return default_columns_for_grid(key)


def catalog_keys_for_grid(grid_key: str, *, tenant_id: str) -> frozenset[str]:
    return frozenset(
        c["column_key"] for c in catalog_columns_for_grid(grid_key, tenant_id=tenant_id)
    )


def _enrich_columns(
    grid_key: str,
    columns: list[dict[str, Any]],
    *,
    catalog: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge stored settings with catalog defaults; keep locked columns visible."""
    defaults = {c["column_key"]: c for c in catalog}
    locked = locked_columns_for_grid(grid_key)
    by_key: dict[str, dict[str, Any]] = {}

    for raw in columns:
        key = raw.get("column_key")
        if not key or key not in defaults:
            continue
        base = defaults[key]
        visible = bool(raw.get("visible", True))
        if key in locked:
            visible = True
        pinned = raw.get("pinned")
        if pinned not in ("left", "right", None):
            pinned = None
        width = raw.get("width")
        if width is not None:
            try:
                width = int(width)
            except (TypeError, ValueError):
                width = None
            if width is not None and (width < 40 or width > 1200):
                width = None
        order = raw.get("order", base["order"])
        try:
            order = int(order)
        except (TypeError, ValueError):
            order = base["order"]
        entry = {
            "column_key": key,
            "label": base["label"],
            "visible": visible,
            "order": order,
            "width": width,
            "pinned": pinned,
            "locked": key in locked,
        }
        if base.get("source"):
            entry["source"] = base["source"]
        if base.get("applies_to") is not None:
            entry["applies_to"] = list(base["applies_to"])
        if base.get("field_type") is not None:
            entry["field_type"] = base["field_type"]
        by_key[key] = entry

    # Ensure every catalog column exists (new custom fields appear after create).
    for key, base in defaults.items():
        if key not in by_key:
            by_key[key] = dict(base)

    ordered = sorted(by_key.values(), key=lambda c: (c["order"], c["column_key"]))
    # Keep Actions last when present.
    if any(c["column_key"] == "actions" for c in ordered):
        ordered = [c for c in ordered if c["column_key"] != "actions"] + [
            next(c for c in ordered if c["column_key"] == "actions")
        ]
    for idx, col in enumerate(ordered):
        col["order"] = idx
    return ordered


def _serialize_config(
    doc: dict[str, Any] | None,
    *,
    grid_key: str,
    tenant_id: str,
) -> dict[str, Any]:
    catalog = catalog_columns_for_grid(grid_key, tenant_id=tenant_id)
    if doc is None:
        return {
            "grid_key": grid_key,
            "tenant_id": tenant_id,
            "columns": catalog,
            "is_default": True,
            "created_at": None,
            "updated_at": None,
        }
    serialized = serialize_document(doc) or {}
    columns = _enrich_columns(
        grid_key, list(serialized.get("columns") or []), catalog=catalog
    )
    return {
        "grid_key": grid_key,
        "tenant_id": serialized.get("tenant_id") or tenant_id,
        "columns": columns,
        "is_default": False,
        "created_at": serialized.get("created_at"),
        "updated_at": serialized.get("updated_at"),
    }


def validate_grid_key(grid_key: str) -> str:
    key = (grid_key or "").strip()
    if key not in GRID_KEYS:
        raise ColumnConfigError(
            f"Unknown grid_key '{grid_key}'. Allowed: {', '.join(sorted(GRID_KEYS))}",
            status_code=404,
        )
    return key


def list_configurations(*, tenant_id: str) -> list[dict[str, Any]]:
    """Return configs for every known grid (defaults when unset)."""
    tid = require_tenant_id(tenant_id)
    return [get_configuration(grid_key, tenant_id=tid) for grid_key in sorted(GRID_KEYS)]


def get_configuration(grid_key: str, *, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    key = validate_grid_key(grid_key)
    doc = _collection().find_one({"grid_key": key, **tenant_filter(tid)})
    return _serialize_config(doc, grid_key=key, tenant_id=tid)


def upsert_configuration(
    grid_key: str,
    payload: ColumnConfigurationUpdate,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    key = validate_grid_key(grid_key)
    catalog = catalog_columns_for_grid(key, tenant_id=tid)
    catalog_keys = frozenset(c["column_key"] for c in catalog)
    locked = locked_columns_for_grid(key)

    incoming = [c.model_dump() for c in payload.columns]
    incoming_keys = {c["column_key"] for c in incoming}
    unknown = incoming_keys - catalog_keys
    if unknown:
        raise ColumnConfigError(
            f"Unknown column_key(s) for grid '{key}': {', '.join(sorted(unknown))}"
        )

    missing_locked = locked - incoming_keys
    if missing_locked:
        raise ColumnConfigError(
            f"Locked columns must be present and cannot be removed: "
            f"{', '.join(sorted(missing_locked))}"
        )

    for col in incoming:
        if col["column_key"] in locked and not col.get("visible", True):
            raise ColumnConfigError(
                f"Column '{col['column_key']}' is locked and must remain visible"
            )

    # Reject attempts to collapse OS/product or protocol/port into combined keys.
    collapsed_forbidden = {
        "os_family_version",
        "os_family_os_version",
        "product_type_version",
        "product_type_product_version",
        "protocol_ports",
        "source_target_port",
        "ports",
    }
    if incoming_keys & collapsed_forbidden:
        raise ColumnConfigError(
            "Collapsed OS/product or protocol/port column keys are not allowed"
        )

    columns = _enrich_columns(key, incoming, catalog=catalog)
    now = _now()
    coll = _collection()
    existing = coll.find_one({"grid_key": key, **tenant_filter(tid)})
    doc: dict[str, Any] = {
        "grid_key": key,
        "columns": [
            {
                "column_key": c["column_key"],
                "visible": c["visible"],
                "order": c["order"],
                "width": c["width"],
                "pinned": c["pinned"],
            }
            for c in columns
        ],
        "updated_at": now,
    }
    stamp_tenant_id(doc, tenant_id=tid)
    if existing is None:
        doc["created_at"] = now
        coll.insert_one(doc)
    else:
        coll.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "columns": doc["columns"],
                    "updated_at": now,
                    "tenant_id": tid,
                }
            },
        )
    return get_configuration(key, tenant_id=tid)


def reset_configuration(grid_key: str, *, tenant_id: str) -> dict[str, Any]:
    """Delete stored config so GET returns catalog defaults."""
    tid = require_tenant_id(tenant_id)
    key = validate_grid_key(grid_key)
    _collection().delete_one({"grid_key": key, **tenant_filter(tid)})
    return get_configuration(key, tenant_id=tid)
