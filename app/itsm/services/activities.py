"""Append-only ticket activity timeline (ITSM DB)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import DESCENDING
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from .indexes import ACTIVITIES, ensure_itsm_indexes


class ActivityError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[ACTIVITIES]


def _new_activity_id() -> str:
    return f"act-{uuid.uuid4().hex[:16]}"


def append_activity(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    activity_type: str,
    message: str,
    actor_user_id: str | None = None,
    actor_username: str | None = None,
    from_value: str | None = None,
    to_value: str | None = None,
    visibility: str = "public",
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    msg = (message or "").strip()
    if not msg:
        raise ActivityError("message is required")
    doc: dict[str, Any] = {
        "activity_id": _new_activity_id(),
        "ticket_type": ticket_type,
        "ticket_id": ticket_id,
        "activity_type": activity_type,
        "message": msg,
        "from_value": from_value,
        "to_value": to_value,
        "actor_user_id": actor_user_id,
        "actor_username": actor_username,
        "visibility": visibility if visibility in {"public", "internal"} else "public",
        "created_at": _now(),
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _coll().insert_one(doc)
    return serialize_document(doc)  # type: ignore[return-value]


def list_activities(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    query = merge_tenant_filter(
        {"ticket_type": ticket_type, "ticket_id": ticket_id},
        tid,
    )
    coll = _coll()
    total = coll.count_documents(query)
    cursor = (
        coll.find(query)
        .sort([("created_at", DESCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "ticket_type": ticket_type,
        "ticket_id": ticket_id,
        "tenant_id": tid,
    }
