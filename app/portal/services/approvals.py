"""Change-driven approval sync for Service Portal (OD-2).

ITSM Change is the source of truth. Portal only mirrors status onto
``sp_requests`` and never owns a decide surface.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...itsm.services import changes as changes_service
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id
from .indexes import REQUESTS, ensure_portal_indexes
from .requests import RequestError, get_request

# Change statuses that mean the portal request is approved (ready for SP6 exec).
_CHANGE_APPROVED = frozenset(
    {"approved", "scheduled", "implementing", "review", "closed"}
)
_CHANGE_REJECTED = frozenset({"rejected"})
_CHANGE_CANCELLED = frozenset({"cancelled"})

# Request statuses that may still be driven by Change sync.
_SYNCABLE_REQUEST = frozenset({"submitted", "pending_approval", "approved"})


class ApprovalError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_portal_indexes()
    return require_itsm_database()[REQUESTS]


def _map_request_status(
    *,
    current_request_status: str,
    change_status: str,
) -> str | None:
    """Return new request status, or None if no change."""
    if current_request_status not in _SYNCABLE_REQUEST and current_request_status not in (
        "rejected",
        "cancelled",
    ):
        # Terminal execution states (queued+) are owned by SP6+.
        return None
    if change_status in _CHANGE_REJECTED:
        if current_request_status != "rejected":
            return "rejected"
        return None
    if change_status in _CHANGE_CANCELLED:
        if current_request_status in ("submitted", "pending_approval", "approved"):
            return "cancelled"
        return None
    if change_status in _CHANGE_APPROVED:
        if current_request_status in ("submitted", "pending_approval"):
            return "approved"
        return None
    # Still waiting (draft/submitted on Change).
    if current_request_status == "submitted":
        return "pending_approval"
    return None


def list_change_status(
    *,
    tenant_id: str,
    status: str | None = None,
    change_status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """List portal requests that have a linked Change (Change-status view)."""
    tid = require_tenant_id(tenant_id)
    clauses: list[dict[str, Any]] = [{"change_id": {"$ne": None}}]
    if status:
        clauses.append({"status": status})
    if change_status:
        clauses.append({"change_status_snapshot": change_status})
    query = merge_tenant_filter({"$and": clauses}, tid)
    coll = _coll()
    total = coll.count_documents(query)
    skip = max(0, (page - 1) * page_size)
    cursor = (
        coll.find(query)
        .sort([("updated_at", -1)])
        .skip(skip)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "approval_sot": "itsm_change",
        "decide_surface": "itsm",
    }


def sync_request_from_change(
    request_id: str,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pull ITSM Change status and mirror onto the portal request."""
    tid = require_tenant_id(tenant_id)
    existing = get_request(tenant_id=tid, request_id=request_id)
    change_id = existing.get("change_id")
    if not change_id:
        raise ApprovalError("request has no linked Change", status_code=400)

    change = changes_service.get_change(change_id, tenant_id=tid)
    if not change:
        raise ApprovalError("linked Change not found", status_code=404)

    change_status = str(change.get("status") or "")
    updates: dict[str, Any] = {
        "change_status_snapshot": change_status,
        "change_number_display": change.get("number_display"),
        "updated_at": _now(),
    }
    actor = actor or {}
    who = actor.get("user_id") or actor.get("username")
    if who:
        updates["updated_by"] = who

    before_status = str(existing.get("status") or "")
    new_status = _map_request_status(
        current_request_status=before_status,
        change_status=change_status,
    )
    if new_status:
        updates["status"] = new_status
        if new_status == "approved":
            updates["approved_at"] = _now()
        elif new_status == "rejected":
            updates["rejected_at"] = _now()
        elif new_status == "cancelled":
            updates["cancelled_at"] = _now()

    result = _coll().find_one_and_update(
        merge_tenant_filter({"request_id": request_id}, tid),
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise ApprovalError("request not found", status_code=404)
    serialized = serialize_document(result)
    assert serialized is not None
    if new_status and new_status != before_status and new_status in (
        "approved",
        "rejected",
        "cancelled",
    ):
        from . import notifications as portal_notifications

        portal_notifications.notify_request_decision(
            tenant_id=tid,
            request=serialized,
            decision=new_status,
            actor=actor,
        )
    return serialized


def sync_pending_requests(
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Sync all submitted/pending_approval requests that have a change_id."""
    tid = require_tenant_id(tenant_id)
    query = merge_tenant_filter(
        {
            "$and": [
                {"change_id": {"$ne": None}},
                {"status": {"$in": list(_SYNCABLE_REQUEST)}},
            ]
        },
        tid,
    )
    cursor = _coll().find(query).sort([("updated_at", 1)]).limit(max(1, min(limit, 500)))
    synced = 0
    transitioned = 0
    errors: list[dict[str, str]] = []
    items: list[dict[str, Any]] = []
    for doc in cursor:
        request_id = doc.get("request_id")
        before = doc.get("status")
        try:
            updated = sync_request_from_change(
                request_id, tenant_id=tid, actor=actor
            )
            synced += 1
            if updated.get("status") != before:
                transitioned += 1
            items.append(updated)
        except (ApprovalError, RequestError) as exc:
            errors.append(
                {
                    "request_id": str(request_id),
                    "error": getattr(exc, "message", str(exc)),
                }
            )
    return {
        "synced": synced,
        "transitioned": transitioned,
        "errors": errors,
        "items": items,
        "approval_sot": "itsm_change",
    }
