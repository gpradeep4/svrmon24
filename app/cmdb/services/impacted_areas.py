"""CMDB CI Impacted Areas (tenant-scoped, C4)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from ...db import require_database
from ...serialization import serialize_document
from ...tenancy import require_tenant_id, stamp_tenant_id
from ..models.impacted_areas import (
    ImpactedAreaCreate,
    ImpactedAreaUpdate,
    to_impacted_area_row,
)
from . import components as components_service

COLLECTION = "cmdb_impacted_areas"


class ImpactedAreaError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _collection() -> Collection:
    coll = require_database()[COLLECTION]
    coll.create_index([("area_id", ASCENDING)], unique=True)
    coll.create_index(
        [("tenant_id", ASCENDING), ("component_id", ASCENDING)],
        name="tenant_component_idx",
    )
    return coll


def _new_area_id() -> str:
    return f"area-{uuid.uuid4().hex[:12]}"


def _require_component(component_id: str, *, tenant_id: str) -> dict[str, Any]:
    doc = components_service.get_component(component_id, tenant_id=tenant_id)
    if doc is None:
        raise ImpactedAreaError(
            f"Component '{component_id}' not found", status_code=404
        )
    return doc


def list_impacted_areas(component_id: str, *, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    cursor = (
        _collection()
        .find({"tenant_id": tid, "component_id": component_id})
        .sort([("updated_at", DESCENDING)])
    )
    items = [to_impacted_area_row(serialize_document(d) or d) for d in cursor]
    return {
        "items": items,
        "total": len(items),
        "component_id": component_id,
        "tenant_id": tid,
    }


def create_impacted_area(
    component_id: str,
    payload: ImpactedAreaCreate,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    now = _now()
    area_id = _new_area_id()
    doc: dict[str, Any] = {
        "area_id": area_id,
        "component_id": component_id,
        "company": payload.company,
        "region": payload.region,
        "site_group": payload.site_group,
        "site": payload.site,
        "organization": payload.organization,
        "department": payload.department,
        "created_at": now,
        "updated_at": now,
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _collection().insert_one(doc)
    return to_impacted_area_row(serialize_document(doc) or doc)


def update_impacted_area(
    component_id: str,
    area_id: str,
    payload: ImpactedAreaUpdate,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    coll = _collection()
    existing = coll.find_one(
        {"tenant_id": tid, "component_id": component_id, "area_id": area_id}
    )
    if existing is None:
        raise ImpactedAreaError(
            f"Impacted area '{area_id}' not found", status_code=404
        )

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return to_impacted_area_row(serialize_document(existing) or existing)

    # Ensure at least one location field remains after merge.
    merged = {**existing, **updates}
    fields = (
        merged.get("company"),
        merged.get("region"),
        merged.get("site_group"),
        merged.get("site"),
        merged.get("organization"),
        merged.get("department"),
    )
    if not any(fields):
        raise ImpactedAreaError(
            "at least one of company/region/site_group/site/organization/department is required"
        )

    updates["updated_at"] = _now()
    coll.update_one(
        {"tenant_id": tid, "component_id": component_id, "area_id": area_id},
        {"$set": updates},
    )
    doc = coll.find_one(
        {"tenant_id": tid, "component_id": component_id, "area_id": area_id}
    )
    return to_impacted_area_row(serialize_document(doc) or doc or {})


def delete_impacted_area(
    component_id: str,
    area_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    result = _collection().delete_one(
        {"tenant_id": tid, "component_id": component_id, "area_id": area_id}
    )
    if result.deleted_count == 0:
        raise ImpactedAreaError(
            f"Impacted area '{area_id}' not found", status_code=404
        )
    return {
        "ok": True,
        "area_id": area_id,
        "component_id": component_id,
        "tenant_id": tid,
    }
