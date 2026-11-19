"""Approvals Management — ITSM DB only; ticket refs validated via ticket services."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from ..models.approvals import (
    APPROVAL_STATUSES,
    APPROVAL_TRANSITIONS,
    ApprovalCreate,
    ApprovalDecide,
    ApprovalUpdate,
)
from ..models.common import TICKET_TYPES
from . import activities as activities_service
from . import changes as changes_service
from . import incidents as incidents_service
from . import problems as problems_service
from .indexes import APPROVALS, ensure_itsm_indexes


class ApprovalError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[APPROVALS]


def _new_approval_id() -> str:
    return f"APR-{uuid.uuid4().hex[:10].upper()}"


def _actor_fields(actor: dict[str, Any] | None) -> dict[str, str | None]:
    actor = actor or {}
    return {
        "user_id": actor.get("user_id") or actor.get("username"),
        "username": actor.get("username") or actor.get("user_id"),
    }


def _clean_id_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def ensure_ticket_exists(ticket_type: str, ticket_id: str, *, tenant_id: str) -> dict[str, Any]:
    if ticket_type not in TICKET_TYPES:
        raise ApprovalError(f"Invalid ticket_type '{ticket_type}'")
    if ticket_type == "incident":
        doc = incidents_service.get_incident(ticket_id, tenant_id=tenant_id)
        label = "Incident"
    elif ticket_type == "change":
        doc = changes_service.get_change(ticket_id, tenant_id=tenant_id)
        label = "Change"
    else:
        doc = problems_service.get_problem(ticket_id, tenant_id=tenant_id)
        label = "Problem"
    if doc is None:
        raise ApprovalError(f"{label} '{ticket_id}' not found", status_code=404)
    return doc


def get_approval(approval_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one({"tenant_id": tid, "approval_id": approval_id})
    return serialize_document(doc)


def list_approvals(
    *,
    tenant_id: str,
    q: str | None = None,
    status: str | None = None,
    ticket_type: str | None = None,
    ticket_id: str | None = None,
    workflow_execution_id: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    clauses: list[dict[str, Any]] = []
    if status:
        if status not in APPROVAL_STATUSES:
            raise ApprovalError(f"Invalid status '{status}'")
        clauses.append({"status": status})
    if ticket_type:
        if ticket_type not in TICKET_TYPES:
            raise ApprovalError(f"Invalid ticket_type '{ticket_type}'")
        clauses.append({"ticket_type": ticket_type})
    if ticket_id:
        clauses.append({"ticket_id": ticket_id.strip()})
    if workflow_execution_id:
        clauses.append({"workflow_execution_id": workflow_execution_id.strip()})
    if q and q.strip():
        term = q.strip()
        clauses.append(
            {
                "$or": [
                    {"title": {"$regex": term, "$options": "i"}},
                    {"approval_id": {"$regex": term, "$options": "i"}},
                    {"ticket_id": {"$regex": term, "$options": "i"}},
                    {"approver_group": {"$regex": term, "$options": "i"}},
                ]
            }
        )

    query: dict[str, Any] = {"tenant_id": tid}
    if clauses:
        query = merge_tenant_filter({"$and": clauses}, tid)

    allowed_sort = {
        "updated_at",
        "created_at",
        "status",
        "title",
        "decided_at",
    }
    if sort_by not in allowed_sort:
        sort_by = "updated_at"
    direction = DESCENDING if str(sort_dir).lower() != "asc" else ASCENDING

    coll = _coll()
    total = coll.count_documents(query)
    cursor = (
        coll.find(query)
        .sort([(sort_by, direction)])
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
        "tenant_id": tid,
    }


def create_approval(
    payload: ApprovalCreate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
    skip_ticket_check: bool = False,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if not skip_ticket_check:
        ensure_ticket_exists(payload.ticket_type, payload.ticket_id, tenant_id=tid)

    who = _actor_fields(actor)
    now = _now()
    approval_id = _new_approval_id()
    doc: dict[str, Any] = {
        "approval_id": approval_id,
        "title": payload.title.strip(),
        "description": (payload.description or "").strip() or None,
        "ticket_type": payload.ticket_type,
        "ticket_id": payload.ticket_id.strip(),
        "status": "pending",
        "approver_user_ids": _clean_id_list(payload.approver_user_ids),
        "approver_group": (payload.approver_group or "").strip() or None,
        "policy": (payload.policy or "").strip() or None,
        "workflow_execution_id": (payload.workflow_execution_id or "").strip() or None,
        "node_id": (payload.node_id or "").strip() or None,
        "decided_by": None,
        "decided_at": None,
        "comment": None,
        "created_at": now,
        "updated_at": now,
        "created_by": who["username"],
        "updated_by": who["username"],
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _coll().insert_one(doc)

    activities_service.append_activity(
        tenant_id=tid,
        ticket_type=payload.ticket_type,
        ticket_id=payload.ticket_id.strip(),
        activity_type="approval",
        message=f"Approval requested: {doc['title']} ({approval_id})",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        to_value="pending",
    )
    return serialize_document(doc)  # type: ignore[return-value]


def update_approval(
    approval_id: str,
    payload: ApprovalUpdate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "approval_id": approval_id})
    if existing is None:
        raise ApprovalError(f"Approval '{approval_id}' not found", status_code=404)
    if existing.get("status") != "pending":
        raise ApprovalError(
            f"Cannot update approval in status '{existing.get('status')}'",
            status_code=409,
        )

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return serialize_document(existing)  # type: ignore[return-value]
    if "approver_user_ids" in updates:
        updates["approver_user_ids"] = _clean_id_list(updates["approver_user_ids"])
    if "title" in updates and updates["title"] is not None:
        updates["title"] = updates["title"].strip()
    if "description" in updates and updates["description"] is not None:
        updates["description"] = updates["description"].strip() or None
    if "approver_group" in updates and updates["approver_group"] is not None:
        updates["approver_group"] = updates["approver_group"].strip() or None
    if "policy" in updates and updates["policy"] is not None:
        updates["policy"] = updates["policy"].strip() or None

    who = _actor_fields(actor)
    updates["updated_at"] = _now()
    updates["updated_by"] = who["username"]

    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "approval_id": approval_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise ApprovalError(f"Approval '{approval_id}' not found", status_code=404)
    return serialize_document(doc)  # type: ignore[return-value]


def decide_approval(
    approval_id: str,
    payload: ApprovalDecide,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
    resume_workflow: bool = True,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "approval_id": approval_id})
    if existing is None:
        raise ApprovalError(f"Approval '{approval_id}' not found", status_code=404)

    current = str(existing.get("status") or "")
    target = payload.decision
    allowed = APPROVAL_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ApprovalError(
            f"Cannot transition approval from '{current}' to '{target}'",
            status_code=409,
        )

    who = _actor_fields(actor)
    now = _now()
    updates: dict[str, Any] = {
        "status": target,
        "decided_by": who["username"],
        "decided_at": now,
        "comment": (payload.comment or "").strip() or None,
        "updated_at": now,
        "updated_by": who["username"],
    }
    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "approval_id": approval_id, "status": "pending"},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise ApprovalError(
            f"Approval '{approval_id}' is no longer pending",
            status_code=409,
        )

    activities_service.append_activity(
        tenant_id=tid,
        ticket_type=str(doc["ticket_type"]),
        ticket_id=str(doc["ticket_id"]),
        activity_type="approval",
        message=f"Approval {target}: {doc.get('title')} ({approval_id})",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        from_value="pending",
        to_value=target,
    )

    if resume_workflow and doc.get("workflow_execution_id"):
        # Lazy import to avoid circular dependency at module load.
        from . import workflow_engine as engine

        try:
            engine.resume_after_approval(
                execution_id=str(doc["workflow_execution_id"]),
                approval_id=approval_id,
                decision=target,
                tenant_id=tid,
                actor=actor,
            )
        except Exception as exc:  # noqa: BLE001 — surface as approval still decided
            # Decision sticks; attach note on approval doc.
            _coll().update_one(
                {"tenant_id": tid, "approval_id": approval_id},
                {
                    "$set": {
                        "workflow_resume_error": str(exc),
                        "updated_at": _now(),
                    }
                },
            )
            refreshed = _coll().find_one({"tenant_id": tid, "approval_id": approval_id})
            return serialize_document(refreshed)  # type: ignore[return-value]

    return serialize_document(doc)  # type: ignore[return-value]


def cancel_approval(
    approval_id: str,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "approval_id": approval_id})
    if existing is None:
        raise ApprovalError(f"Approval '{approval_id}' not found", status_code=404)
    if existing.get("status") != "pending":
        raise ApprovalError(
            f"Cannot cancel approval in status '{existing.get('status')}'",
            status_code=409,
        )
    who = _actor_fields(actor)
    now = _now()
    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "approval_id": approval_id, "status": "pending"},
        {
            "$set": {
                "status": "cancelled",
                "decided_by": who["username"],
                "decided_at": now,
                "comment": (comment or "").strip() or None,
                "updated_at": now,
                "updated_by": who["username"],
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise ApprovalError(f"Approval '{approval_id}' not found", status_code=404)

    activities_service.append_activity(
        tenant_id=tid,
        ticket_type=str(doc["ticket_type"]),
        ticket_id=str(doc["ticket_id"]),
        activity_type="approval",
        message=f"Approval cancelled: {doc.get('title')} ({approval_id})",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        from_value="pending",
        to_value="cancelled",
    )
    return serialize_document(doc)  # type: ignore[return-value]
