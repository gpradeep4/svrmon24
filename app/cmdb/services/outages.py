"""CMDB CI Outages (tenant-scoped, C4)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from ...db import require_database
from ...serialization import serialize_document
from ...tenancy import require_tenant_id, stamp_tenant_id
from ..models.outages import OutageCreate, OutageUpdate, to_outage_row
from . import components as components_service

COLLECTION = "cmdb_ci_outages"


class OutageError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _collection() -> Collection:
    coll = require_database()[COLLECTION]
    coll.create_index([("outage_id", ASCENDING)], unique=True)
    coll.create_index(
        [("tenant_id", ASCENDING), ("component_id", ASCENDING)],
        name="tenant_component_idx",
    )
    coll.create_index(
        [
            ("tenant_id", ASCENDING),
            ("component_id", ASCENDING),
            ("starts_at", DESCENDING),
        ],
        name="tenant_component_starts_idx",
    )
    return coll


def _new_outage_id() -> str:
    return f"out-{uuid.uuid4().hex[:12]}"


def _require_component(component_id: str, *, tenant_id: str) -> dict[str, Any]:
    doc = components_service.get_component(component_id, tenant_id=tenant_id)
    if doc is None:
        raise OutageError(
            f"Component '{component_id}' not found", status_code=404
        )
    return doc


def _serialize_ref(ref: Any) -> dict[str, str] | None:
    if ref is None:
        return None
    if hasattr(ref, "model_dump"):
        return ref.model_dump()
    if isinstance(ref, dict):
        return {"module": ref["module"], "ticket_id": ref["ticket_id"]}
    return None


def list_outages(component_id: str, *, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    cursor = (
        _collection()
        .find({"tenant_id": tid, "component_id": component_id})
        .sort([("starts_at", DESCENDING), ("updated_at", DESCENDING)])
    )
    items = [to_outage_row(serialize_document(d) or d) for d in cursor]
    return {
        "items": items,
        "total": len(items),
        "component_id": component_id,
        "tenant_id": tid,
    }


def get_outage(
    component_id: str,
    outage_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    doc = _collection().find_one(
        {
            "tenant_id": tid,
            "component_id": component_id,
            "outage_id": outage_id,
        }
    )
    if doc is None:
        raise OutageError(f"Outage '{outage_id}' not found", status_code=404)
    return to_outage_row(serialize_document(doc) or doc)


def create_outage(
    component_id: str,
    payload: OutageCreate,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    now = _now()
    outage_id = _new_outage_id()
    doc: dict[str, Any] = {
        "outage_id": outage_id,
        "component_id": component_id,
        "unavailability_class": payload.unavailability_class,
        "unavailability_type": payload.unavailability_type,
        "status": payload.status,
        "assignment_status": payload.assignment_status,
        "starts_at": payload.starts_at,
        "ends_at": payload.ends_at,
        "summary": payload.summary,
        "itsm_ref": _serialize_ref(payload.itsm_ref),
        "created_at": now,
        "updated_at": now,
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _collection().insert_one(doc)
    return to_outage_row(serialize_document(doc) or doc)


def update_outage(
    component_id: str,
    outage_id: str,
    payload: OutageUpdate,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    coll = _collection()
    existing = coll.find_one(
        {
            "tenant_id": tid,
            "component_id": component_id,
            "outage_id": outage_id,
        }
    )
    if existing is None:
        raise OutageError(f"Outage '{outage_id}' not found", status_code=404)

    updates = payload.model_dump(exclude_unset=True)
    if "itsm_ref" in updates:
        updates["itsm_ref"] = _serialize_ref(updates.get("itsm_ref"))
    if not updates:
        return to_outage_row(serialize_document(existing) or existing)

    updates["updated_at"] = _now()
    coll.update_one(
        {
            "tenant_id": tid,
            "component_id": component_id,
            "outage_id": outage_id,
        },
        {"$set": updates},
    )
    doc = coll.find_one(
        {
            "tenant_id": tid,
            "component_id": component_id,
            "outage_id": outage_id,
        }
    )
    return to_outage_row(serialize_document(doc) or doc or {})


def delete_outage(
    component_id: str,
    outage_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    result = _collection().delete_one(
        {
            "tenant_id": tid,
            "component_id": component_id,
            "outage_id": outage_id,
        }
    )
    if result.deleted_count == 0:
        raise OutageError(f"Outage '{outage_id}' not found", status_code=404)
    return {
        "ok": True,
        "outage_id": outage_id,
        "component_id": component_id,
        "tenant_id": tid,
    }
