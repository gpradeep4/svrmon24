"""Service Portal catalog CRUD + seed (ITSM DB ``sp_catalog_items``)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from ..models.catalog import (
    CATALOG_DOMAINS,
    CatalogItemCreate,
    CatalogItemUpdate,
    FormSchema,
)
from .indexes import CATALOG_ITEMS, ensure_portal_indexes
from .seed import ACTION_KEY_ALLOWLIST, seed_catalog_specs


class CatalogError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_portal_indexes()
    return require_itsm_database()[CATALOG_ITEMS]


def _new_item_id() -> str:
    return f"SPI-{uuid.uuid4().hex[:10].upper()}"


def _validate_action_key(action_key: str) -> None:
    if action_key not in ACTION_KEY_ALLOWLIST:
        raise CatalogError(
            f"action_key '{action_key}' is not in the allowlist",
            status_code=400,
        )


def list_catalog(
    *,
    tenant_id: str,
    domain: str | None = None,
    enabled: bool | None = True,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    clauses: list[dict[str, Any]] = []
    if domain:
        if domain not in CATALOG_DOMAINS:
            raise CatalogError(f"invalid domain '{domain}'")
        clauses.append({"domain": domain})
    if enabled is not None:
        clauses.append({"enabled": bool(enabled)})
    if q:
        rx = {"$regex": q.strip(), "$options": "i"}
        clauses.append(
            {
                "$or": [
                    {"title": rx},
                    {"key": rx},
                    {"description": rx},
                    {"action_key": rx},
                ]
            }
        )
    query = merge_tenant_filter(tid, {"$and": clauses} if clauses else {})
    coll = _coll()
    total = coll.count_documents(query)
    skip = max(0, (page - 1) * page_size)
    cursor = (
        coll.find(query)
        .sort([("domain", 1), ("title", 1)])
        .skip(skip)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "domains": list(CATALOG_DOMAINS),
    }


def get_catalog_item(*, tenant_id: str, item_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one(merge_tenant_filter(tid, {"item_id": item_id}))
    if not doc:
        raise CatalogError("catalog item not found", status_code=404)
    return serialize_document(doc)


def get_catalog_item_by_key(*, tenant_id: str, key: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one(merge_tenant_filter(tid, {"key": key}))
    return serialize_document(doc) if doc else None


def create_catalog_item(
    payload: CatalogItemCreate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _validate_action_key(payload.action_key)
    if payload.default_collect_mode not in payload.allowed_collect_modes:
        raise CatalogError("default_collect_mode must be in allowed_collect_modes")
    now = _now()
    actor = actor or {}
    doc = stamp_tenant_id(
        {
            "item_id": _new_item_id(),
            "key": payload.key,
            "title": payload.title,
            "description": payload.description,
            "domain": payload.domain,
            "action_key": payload.action_key,
            "form_schema": payload.form_schema.model_dump(),
            "change_type_key": payload.change_type_key,
            "itsm_change_type": payload.itsm_change_type,
            "change_workflow_key": payload.change_workflow_key,
            "risk_tier": payload.risk_tier,
            "enabled": payload.enabled,
            "supports_dry_run": payload.supports_dry_run,
            "default_execution_mode": payload.default_execution_mode,
            "allowed_collect_modes": list(payload.allowed_collect_modes),
            "default_collect_mode": payload.default_collect_mode,
            "target_placement": payload.target_placement,
            "cmdb_sync": payload.cmdb_sync,
            "cmdb_component_type": payload.cmdb_component_type,
            "cmdb_field_map": dict(payload.cmdb_field_map or {}),
            "adapter": payload.adapter,
            "schema_version": payload.schema_version,
            "created_at": now,
            "updated_at": now,
            "created_by": actor.get("user_id") or actor.get("username"),
            "updated_by": actor.get("user_id") or actor.get("username"),
        },
        tid,
    )
    try:
        _coll().insert_one(doc)
    except Exception as exc:  # noqa: BLE001 — duplicate key
        if "duplicate" in str(exc).lower() or getattr(exc, "code", None) == 11000:
            raise CatalogError("catalog key already exists", status_code=409) from exc
        raise
    return serialize_document(doc)


def update_catalog_item(
    item_id: str,
    payload: CatalogItemUpdate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    updates = payload.model_dump(exclude_unset=True)
    if "form_schema" in updates and updates["form_schema"] is not None:
        updates["form_schema"] = FormSchema.model_validate(
            updates["form_schema"]
        ).model_dump()
    if "allowed_collect_modes" in updates and updates["allowed_collect_modes"]:
        default_mode = updates.get("default_collect_mode")
        existing = get_catalog_item(tenant_id=tid, item_id=item_id)
        check_default = default_mode or existing.get("default_collect_mode")
        if check_default not in updates["allowed_collect_modes"]:
            raise CatalogError("default_collect_mode must be in allowed_collect_modes")
    if not updates:
        return get_catalog_item(tenant_id=tid, item_id=item_id)
    actor = actor or {}
    updates["updated_at"] = _now()
    updates["updated_by"] = actor.get("user_id") or actor.get("username")
    if "schema_version" not in updates:
        # Bump schema_version on form_schema edits.
        if "form_schema" in updates:
            existing = get_catalog_item(tenant_id=tid, item_id=item_id)
            updates["schema_version"] = int(existing.get("schema_version") or 1) + 1
    result = _coll().find_one_and_update(
        merge_tenant_filter(tid, {"item_id": item_id}),
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise CatalogError("catalog item not found", status_code=404)
    return serialize_document(result)


def seed_catalog(*, tenant_id: str, actor: dict[str, Any] | None = None) -> dict[str, Any]:
    """Upsert seed items by key for the tenant (idempotent)."""
    tid = require_tenant_id(tenant_id)
    created = 0
    updated = 0
    for spec in seed_catalog_specs():
        existing = get_catalog_item_by_key(tenant_id=tid, key=spec["key"])
        payload = CatalogItemCreate.model_validate(spec)
        if existing:
            patch = CatalogItemUpdate(
                title=payload.title,
                description=payload.description,
                form_schema=payload.form_schema,
                change_type_key=payload.change_type_key,
                itsm_change_type=payload.itsm_change_type,
                risk_tier=payload.risk_tier,
                enabled=True,
                supports_dry_run=payload.supports_dry_run,
                allowed_collect_modes=payload.allowed_collect_modes,
                default_collect_mode=payload.default_collect_mode,
                target_placement=payload.target_placement,
                cmdb_sync=payload.cmdb_sync,
                cmdb_component_type=payload.cmdb_component_type,
                cmdb_field_map=payload.cmdb_field_map,
            )
            update_catalog_item(
                existing["item_id"], patch, tenant_id=tid, actor=actor
            )
            updated += 1
        else:
            create_catalog_item(payload, tenant_id=tid, actor=actor)
            created += 1
    return {
        "created": created,
        "updated": updated,
        "total_seed": len(seed_catalog_specs()),
        "domains": list(CATALOG_DOMAINS),
        "action_keys": sorted(ACTION_KEY_ALLOWLIST),
    }


def validate_values_for_item(
    *,
    tenant_id: str,
    item_id: str,
    form_values: dict[str, Any] | None,
) -> dict[str, Any]:
    from .form_validate import FormValidationError, validate_form_values

    item = get_catalog_item(tenant_id=tenant_id, item_id=item_id)
    try:
        return validate_form_values(item.get("form_schema") or {}, form_values)
    except FormValidationError as exc:
        raise CatalogError(
            "form validation failed",
            status_code=400,
        ) from exc
