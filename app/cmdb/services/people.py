"""CMDB CI People / support-group links (tenant-scoped, C3)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from ...db import require_database
from ...serialization import serialize_document
from ...tenancy import require_tenant_id, stamp_tenant_id
from ..models.people import PeopleLinkCreate, PeopleLinkUpdate, to_people_row
from . import components as components_service
from .components import ComponentError

COLLECTION = "cmdb_ci_people"


class PeopleError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _collection() -> Collection:
    coll = require_database()[COLLECTION]
    coll.create_index([("link_id", ASCENDING)], unique=True)
    coll.create_index(
        [("tenant_id", ASCENDING), ("component_id", ASCENDING)],
        name="tenant_component_idx",
    )
    coll.create_index(
        [
            ("tenant_id", ASCENDING),
            ("component_id", ASCENDING),
            ("primary_contact", ASCENDING),
        ],
        name="tenant_component_primary_idx",
    )
    return coll


def _new_link_id() -> str:
    return f"plk-{uuid.uuid4().hex[:12]}"


def _require_component(component_id: str, *, tenant_id: str) -> dict[str, Any]:
    doc = components_service.get_component(component_id, tenant_id=tenant_id)
    if doc is None:
        raise PeopleError(
            f"Component '{component_id}' not found", status_code=404
        )
    return doc


def list_people(
    component_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    cursor = (
        _collection()
        .find({"tenant_id": tid, "component_id": component_id})
        .sort([("primary_contact", DESCENDING), ("updated_at", DESCENDING)])
    )
    items = [to_people_row(serialize_document(d) or d) for d in cursor]
    return {
        "items": items,
        "total": len(items),
        "component_id": component_id,
        "tenant_id": tid,
    }


def get_primary_contact(
    component_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any] | None:
    """Return the primary people link for ITSM assignment hints (API-only)."""
    tid = require_tenant_id(tenant_id)
    doc = _collection().find_one(
        {
            "tenant_id": tid,
            "component_id": component_id,
            "primary_contact": True,
        }
    )
    if doc is None:
        return None
    return to_people_row(serialize_document(doc) or doc)


def create_people_link(
    component_id: str,
    payload: PeopleLinkCreate,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    now = _now()
    link_id = _new_link_id()
    doc: dict[str, Any] = {
        "link_id": link_id,
        "component_id": component_id,
        "party_type": payload.party_type.value,
        "party_id": payload.party_id,
        "display_name": payload.display_name,
        "role": payload.role,
        "primary_contact": bool(payload.primary_contact),
        "notify_on_unavailability": bool(payload.notify_on_unavailability),
        "assignment_enabled": bool(payload.assignment_enabled),
        "access_permission": bool(payload.access_permission),
        "created_at": now,
        "updated_at": now,
    }
    stamp_tenant_id(doc, tenant_id=tid)
    if doc["primary_contact"]:
        _clear_other_primaries(component_id, tenant_id=tid, except_link_id=None)
    _collection().insert_one(doc)
    return to_people_row(serialize_document(doc) or doc)


def update_people_link(
    component_id: str,
    link_id: str,
    payload: PeopleLinkUpdate,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    coll = _collection()
    existing = coll.find_one(
        {"tenant_id": tid, "component_id": component_id, "link_id": link_id}
    )
    if existing is None:
        raise PeopleError(f"People link '{link_id}' not found", status_code=404)

    updates = payload.model_dump(exclude_unset=True)
    if "party_type" in updates and updates["party_type"] is not None:
        updates["party_type"] = (
            updates["party_type"].value
            if hasattr(updates["party_type"], "value")
            else updates["party_type"]
        )
    if not updates:
        return to_people_row(serialize_document(existing) or existing)

    if updates.get("primary_contact") is True:
        _clear_other_primaries(component_id, tenant_id=tid, except_link_id=link_id)

    updates["updated_at"] = _now()
    coll.update_one(
        {"tenant_id": tid, "component_id": component_id, "link_id": link_id},
        {"$set": updates},
    )
    doc = coll.find_one(
        {"tenant_id": tid, "component_id": component_id, "link_id": link_id}
    )
    return to_people_row(serialize_document(doc) or doc or {})


def delete_people_link(
    component_id: str,
    link_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    result = _collection().delete_one(
        {"tenant_id": tid, "component_id": component_id, "link_id": link_id}
    )
    if result.deleted_count == 0:
        raise PeopleError(f"People link '{link_id}' not found", status_code=404)
    return {"ok": True, "link_id": link_id, "component_id": component_id, "tenant_id": tid}


def _clear_other_primaries(
    component_id: str,
    *,
    tenant_id: str,
    except_link_id: str | None,
) -> None:
    query: dict[str, Any] = {
        "tenant_id": tenant_id,
        "component_id": component_id,
        "primary_contact": True,
    }
    if except_link_id:
        query["link_id"] = {"$ne": except_link_id}
    _collection().update_many(query, {"$set": {"primary_contact": False}})


def people_error_from_component(exc: ComponentError) -> PeopleError:
    return PeopleError(exc.message, status_code=exc.status_code)
