"""Incident Management service — ITSM DB only; CI validation via CMDB services."""

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
from ..models.common import INCIDENT_PRIORITIES, INCIDENT_STATUSES, INCIDENT_TRANSITIONS
from ..models.incidents import (
    IncidentCreate,
    IncidentTransition,
    IncidentUpdate,
)
from . import activities as activities_service
from .cmdb_links import CmdbLinkError, resolve_ci_links, resolve_component_link
from .indexes import COUNTERS, INCIDENTS, ensure_itsm_indexes


class IncidentError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[INCIDENTS]


def _counters() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[COUNTERS]


def _new_incident_id() -> str:
    return f"INC-{uuid.uuid4().hex[:10].upper()}"


def _next_number(*, tenant_id: str) -> int:
    """Per-tenant monotonic incident number."""
    tid = require_tenant_id(tenant_id)
    doc = _counters().find_one_and_update(
        {"tenant_id": tid, "counter_key": "incident"},
        {"$inc": {"value": 1}, "$setOnInsert": {"tenant_id": tid, "counter_key": "incident"}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc.get("value") or 1)


def _actor_fields(actor: dict[str, Any] | None) -> dict[str, str | None]:
    actor = actor or {}
    return {
        "user_id": actor.get("user_id") or actor.get("username"),
        "username": actor.get("username") or actor.get("user_id"),
    }


def get_incident(incident_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one({"tenant_id": tid, "incident_id": incident_id})
    return serialize_document(doc)


def list_incidents(
    *,
    tenant_id: str,
    q: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assignee_user_id: str | None = None,
    component_id: str | None = None,
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
        if status not in INCIDENT_STATUSES:
            raise IncidentError(f"Invalid status '{status}'")
        clauses.append({"status": status})
    if priority:
        if priority not in INCIDENT_PRIORITIES:
            raise IncidentError(f"Invalid priority '{priority}'")
        clauses.append({"priority": priority})
    if assignee_user_id:
        clauses.append({"assignee_user_id": assignee_user_id.strip()})
    if component_id:
        clauses.append({"ci_links.component_id": component_id.strip()})
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        clauses.append(
            {
                "$or": [
                    {"title": rx},
                    {"description": rx},
                    {"incident_id": rx},
                    {"number_display": rx},
                    {"category": rx},
                    {"assignee_user_id": rx},
                ]
            }
        )
    query: dict[str, Any] | None = {"$and": clauses} if clauses else None
    scoped = merge_tenant_filter(query, tid)

    allowed_sort = {
        "updated_at",
        "created_at",
        "number",
        "status",
        "priority",
        "title",
        "incident_id",
    }
    sort_field = sort_by if sort_by in allowed_sort else "updated_at"
    direction = DESCENDING if str(sort_dir).lower() != "asc" else ASCENDING

    coll = _coll()
    total = coll.count_documents(scoped)
    cursor = (
        coll.find(scoped)
        .sort([(sort_field, direction)])
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


def create_incident(
    payload: IncidentCreate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if payload.status not in INCIDENT_STATUSES:
        raise IncidentError(f"Invalid status '{payload.status}'")
    if payload.priority not in INCIDENT_PRIORITIES:
        raise IncidentError(f"Invalid priority '{payload.priority}'")

    try:
        ci_links = resolve_ci_links(payload.ci_links, tenant_id=tid)
    except CmdbLinkError as exc:
        raise IncidentError(exc.message, status_code=exc.status_code) from exc

    now = _now()
    number = _next_number(tenant_id=tid)
    incident_id = _new_incident_id()
    who = _actor_fields(actor)
    doc: dict[str, Any] = {
        "incident_id": incident_id,
        "number": number,
        "number_display": f"INC-{number:05d}",
        "title": payload.title.strip(),
        "description": (payload.description or "").strip() or None,
        "status": payload.status,
        "priority": payload.priority,
        "urgency": payload.urgency,
        "impact": payload.impact,
        "category": payload.category,
        "subcategory": payload.subcategory,
        "assignment_group": payload.assignment_group,
        "assignee_user_id": payload.assignee_user_id,
        "caller_user_id": payload.caller_user_id,
        "caller_email": payload.caller_email,
        "service_tier": (payload.service_tier or "").strip() or None,
        "customer_class": (payload.customer_class or "").strip() or None,
        "ci_tier": (payload.ci_tier or "").strip() or None,
        "ci_criticality": (payload.ci_criticality or "").strip() or None,
        "ci_links": ci_links,
        "resolution_notes": payload.resolution_notes,
        "problem_id": (payload.problem_id or "").strip() or None,
        "change_id": (payload.change_id or "").strip() or None,
        "sla_tracking_ids": [],
        "resolved_at": now if payload.status == "resolved" else None,
        "closed_at": now if payload.status == "closed" else None,
        "created_at": now,
        "updated_at": now,
        "created_by": who["username"],
        "updated_by": who["username"],
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _coll().insert_one(doc)

    activities_service.append_activity(
        tenant_id=tid,
        ticket_type="incident",
        ticket_id=incident_id,
        activity_type="created",
        message=f"Incident created ({doc['number_display']})",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        to_value=payload.status,
    )
    from . import sla as sla_service

    sla_service.notify_ticket_created(
        tenant_id=tid,
        ticket_type="incident",
        ticket_id=incident_id,
        priority=payload.priority,
        status=payload.status,
        actor=actor,
    )
    refreshed = _coll().find_one({"tenant_id": tid, "incident_id": incident_id})
    return serialize_document(refreshed or doc)  # type: ignore[return-value]


def update_incident(
    incident_id: str,
    payload: IncidentUpdate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "incident_id": incident_id})
    if existing is None:
        raise IncidentError(f"Incident '{incident_id}' not found", status_code=404)

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return serialize_document(existing)  # type: ignore[return-value]

    if "priority" in updates and updates["priority"] not in INCIDENT_PRIORITIES:
        raise IncidentError(f"Invalid priority '{updates['priority']}'")

    who = _actor_fields(actor)
    updates["updated_at"] = _now()
    updates["updated_by"] = who["username"]

    # Track assignment changes for activity.
    old_assignee = existing.get("assignee_user_id")
    new_assignee = updates.get("assignee_user_id", old_assignee)
    unset_fields = payload.model_dump(exclude_unset=True)

    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "incident_id": incident_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise IncidentError(f"Incident '{incident_id}' not found", status_code=404)

    if "assignee_user_id" in unset_fields and old_assignee != new_assignee:
        activities_service.append_activity(
            tenant_id=tid,
            ticket_type="incident",
            ticket_id=incident_id,
            activity_type="assignment",
            message="Assignee updated",
            actor_user_id=who["user_id"],
            actor_username=who["username"],
            from_value=old_assignee,
            to_value=new_assignee,
        )
        from . import notifications as notifications_service

        notifications_service.notify_assignment(
            tenant_id=tid,
            ticket_type="incident",
            ticket_id=incident_id,
            assignee_user_id=new_assignee,
            number_display=doc.get("number_display"),
            actor=actor,
        )
    else:
        activities_service.append_activity(
            tenant_id=tid,
            ticket_type="incident",
            ticket_id=incident_id,
            activity_type="system",
            message="Incident details updated",
            actor_user_id=who["user_id"],
            actor_username=who["username"],
        )
    from . import sla as sla_service

    if sla_service.match_context_changed(existing, doc):
        sla_service.notify_context_changed(
            tenant_id=tid,
            ticket_type="incident",
            ticket_id=incident_id,
            priority=str(doc.get("priority") or existing.get("priority") or "p3"),
            status=str(doc.get("status") or "new"),
            actor=actor,
            ticket=doc,
            reason="context_change",
        )
        refreshed = _coll().find_one({"tenant_id": tid, "incident_id": incident_id})
        if refreshed is not None:
            doc = refreshed
    return serialize_document(doc)  # type: ignore[return-value]


def transition_incident(
    incident_id: str,
    payload: IncidentTransition,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "incident_id": incident_id})
    if existing is None:
        raise IncidentError(f"Incident '{incident_id}' not found", status_code=404)

    current = str(existing.get("status") or "")
    target = payload.status
    if target not in INCIDENT_STATUSES:
        raise IncidentError(f"Invalid status '{target}'")
    allowed = INCIDENT_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise IncidentError(
            f"Cannot transition from '{current}' to '{target}'",
            status_code=409,
        )

    who = _actor_fields(actor)
    now = _now()
    updates: dict[str, Any] = {
        "status": target,
        "updated_at": now,
        "updated_by": who["username"],
    }
    if payload.resolution_notes is not None:
        updates["resolution_notes"] = payload.resolution_notes
    if target == "resolved":
        updates["resolved_at"] = now
    if target == "closed":
        updates["closed_at"] = now
        if not existing.get("resolved_at"):
            updates["resolved_at"] = now

    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "incident_id": incident_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise IncidentError(f"Incident '{incident_id}' not found", status_code=404)

    msg = payload.comment or f"Status changed from {current} to {target}"
    activities_service.append_activity(
        tenant_id=tid,
        ticket_type="incident",
        ticket_id=incident_id,
        activity_type="status_change",
        message=msg,
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        from_value=current,
        to_value=target,
    )
    from . import notifications as notifications_service
    from . import sla as sla_service

    sla_service.notify_status_changed(
        tenant_id=tid,
        ticket_type="incident",
        ticket_id=incident_id,
        from_status=current,
        to_status=target,
        priority=str(doc.get("priority") or "p3"),
        actor=actor,
    )
    notifications_service.notify_status_change(
        tenant_id=tid,
        ticket_type="incident",
        ticket_id=incident_id,
        from_status=current,
        to_status=target,
        assignee_user_id=doc.get("assignee_user_id"),
        number_display=doc.get("number_display"),
        actor=actor,
    )
    return serialize_document(doc)  # type: ignore[return-value]


def add_ci_link(
    incident_id: str,
    *,
    component_id: str,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "incident_id": incident_id})
    if existing is None:
        raise IncidentError(f"Incident '{incident_id}' not found", status_code=404)

    try:
        link = resolve_component_link(component_id, tenant_id=tid)
    except CmdbLinkError as exc:
        raise IncidentError(exc.message, status_code=exc.status_code) from exc

    links = list(existing.get("ci_links") or [])
    if any(str(x.get("component_id")) == link["component_id"] for x in links):
        return serialize_document(existing)  # type: ignore[return-value]

    links.append(link)
    who = _actor_fields(actor)
    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "incident_id": incident_id},
        {
            "$set": {
                "ci_links": links,
                "updated_at": _now(),
                "updated_by": who["username"],
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    activities_service.append_activity(
        tenant_id=tid,
        ticket_type="incident",
        ticket_id=incident_id,
        activity_type="ci_link",
        message=f"Linked CI {link['component_id']}",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        to_value=link["component_id"],
    )
    return serialize_document(doc)  # type: ignore[return-value]


def remove_ci_link(
    incident_id: str,
    *,
    component_id: str,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "incident_id": incident_id})
    if existing is None:
        raise IncidentError(f"Incident '{incident_id}' not found", status_code=404)

    cid = component_id.strip()
    links = [x for x in (existing.get("ci_links") or []) if str(x.get("component_id")) != cid]
    if len(links) == len(existing.get("ci_links") or []):
        raise IncidentError(
            f"CI link '{cid}' not found on incident",
            status_code=404,
        )

    who = _actor_fields(actor)
    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "incident_id": incident_id},
        {
            "$set": {
                "ci_links": links,
                "updated_at": _now(),
                "updated_by": who["username"],
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    activities_service.append_activity(
        tenant_id=tid,
        ticket_type="incident",
        ticket_id=incident_id,
        activity_type="ci_link",
        message=f"Unlinked CI {cid}",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        from_value=cid,
    )
    return serialize_document(doc)  # type: ignore[return-value]
