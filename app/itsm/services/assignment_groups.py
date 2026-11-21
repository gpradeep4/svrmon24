"""Tenant-scoped assignment group directory (ITSM DB only)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from ..models.assignment_groups import AssignmentGroupCreate, AssignmentGroupUpdate
from .indexes import ASSIGNMENT_GROUPS, ensure_itsm_indexes

_NAME_RE = re.compile(r"^[\w ./\-]{1,128}$", re.UNICODE)


class AssignmentGroupError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[ASSIGNMENT_GROUPS]


def _new_group_id() -> str:
    return f"AG-{uuid.uuid4().hex[:10].upper()}"


def _actor_fields(actor: dict[str, Any] | None) -> dict[str, str | None]:
    actor = actor or {}
    return {
        "user_id": actor.get("user_id") or actor.get("username"),
        "username": actor.get("username") or actor.get("user_id"),
    }


def _normalize_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise AssignmentGroupError("Group name is required")
    if not _NAME_RE.match(cleaned):
        raise AssignmentGroupError(
            "Group name may contain letters, digits, spaces, . / - _ only"
        )
    return cleaned


def get_group(group_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one({"tenant_id": tid, "group_id": group_id})
    return serialize_document(doc) if doc else None  # type: ignore[return-value]


def find_group_by_name(name: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    key = (name or "").strip().lower()
    if not key:
        return None
    doc = _coll().find_one({"tenant_id": tid, "name_lower": key})
    return serialize_document(doc) if doc else None  # type: ignore[return-value]


def list_groups(
    *,
    tenant_id: str,
    q: str | None = None,
    active: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    filt: dict[str, Any] = merge_tenant_filter({}, tenant_id=tid)
    if active is not None:
        filt["active"] = bool(active)
    query = (q or "").strip()
    if query:
        rx = {"$regex": re.escape(query), "$options": "i"}
        filt["$or"] = [{"name": rx}, {"group_id": rx}, {"description": rx}]
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))
    total = _coll().count_documents(filt)
    cursor = (
        _coll()
        .find(filt)
        .sort([("name_lower", ASCENDING), ("created_at", DESCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_document(d) for d in cursor]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "tenant_id": tid,
    }


def create_group(
    payload: AssignmentGroupCreate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    name = _normalize_name(payload.name)
    name_lower = name.lower()
    existing = _coll().find_one({"tenant_id": tid, "name_lower": name_lower})
    if existing is not None:
        raise AssignmentGroupError(
            f"Assignment group '{name}' already exists", status_code=409
        )
    who = _actor_fields(actor)
    now = _now()
    group_id = _new_group_id()
    doc: dict[str, Any] = {
        "group_id": group_id,
        "name": name,
        "name_lower": name_lower,
        "description": (payload.description or None),
        "email": (payload.email or None),
        "member_user_ids": list(payload.member_user_ids or []),
        "active": bool(payload.active),
        "created_at": now,
        "updated_at": now,
        "created_by": who["username"],
        "updated_by": who["username"],
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _coll().insert_one(doc)
    return serialize_document(doc)  # type: ignore[return-value]


def update_group(
    group_id: str,
    payload: AssignmentGroupUpdate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "group_id": group_id})
    if existing is None:
        raise AssignmentGroupError(
            f"Assignment group '{group_id}' not found", status_code=404
        )
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return serialize_document(existing)  # type: ignore[return-value]

    if "name" in updates and updates["name"] is not None:
        name = _normalize_name(str(updates["name"]))
        name_lower = name.lower()
        clash = _coll().find_one(
            {
                "tenant_id": tid,
                "name_lower": name_lower,
                "group_id": {"$ne": group_id},
            }
        )
        if clash is not None:
            raise AssignmentGroupError(
                f"Assignment group '{name}' already exists", status_code=409
            )
        updates["name"] = name
        updates["name_lower"] = name_lower

    who = _actor_fields(actor)
    updates["updated_at"] = _now()
    updates["updated_by"] = who["username"]
    updated = _coll().find_one_and_update(
        {"tenant_id": tid, "group_id": group_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise AssignmentGroupError(
            f"Assignment group '{group_id}' not found", status_code=404
        )
    return serialize_document(updated)  # type: ignore[return-value]


def delete_group(group_id: str, *, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    result = _coll().delete_one({"tenant_id": tid, "group_id": group_id})
    if result.deleted_count == 0:
        raise AssignmentGroupError(
            f"Assignment group '{group_id}' not found", status_code=404
        )
    return {"ok": True, "group_id": group_id, "tenant_id": tid}


def picker_names(*, tenant_id: str, active_only: bool = True) -> list[str]:
    """Return sorted group names for datalist pickers."""
    tid = require_tenant_id(tenant_id)
    filt: dict[str, Any] = {"tenant_id": tid}
    if active_only:
        filt["active"] = True
    names = [
        str(d.get("name") or "").strip()
        for d in _coll().find(filt, {"name": 1}).sort("name_lower", ASCENDING)
    ]
    return [n for n in names if n]
