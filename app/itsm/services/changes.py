"""Change Management service — ITSM DB only; CI validation via CMDB services."""

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
from ..models.changes import ChangeCreate, ChangeTransition, ChangeUpdate
from ..models.common import (
    CHANGE_STATUSES,
    CHANGE_TRANSITIONS,
    CHANGE_TYPES,
    INCIDENT_PRIORITIES,
)
from . import activities as activities_service
from .cmdb_links import CmdbLinkError, resolve_ci_links, resolve_component_link
from .indexes import CHANGES, COUNTERS, ensure_itsm_indexes


class ChangeError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[CHANGES]


def _counters() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[COUNTERS]


def _new_change_id() -> str:
    return f"CHG-{uuid.uuid4().hex[:10].upper()}"


def _next_number(*, tenant_id: str) -> int:
    tid = require_tenant_id(tenant_id)
    doc = _counters().find_one_and_update(
        {"tenant_id": tid, "counter_key": "change"},
        {"$inc": {"value": 1}, "$setOnInsert": {"tenant_id": tid, "counter_key": "change"}},
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


def get_change(change_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one({"tenant_id": tid, "change_id": change_id})
    return serialize_document(doc)


def list_changes(
    *,
    tenant_id: str,
    q: str | None = None,
    status: str | None = None,
    change_type: str | None = None,
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
        if status not in CHANGE_STATUSES:
            raise ChangeError(f"Invalid status '{status}'")
        clauses.append({"status": status})
    if change_type:
        if change_type not in CHANGE_TYPES:
            raise ChangeError(f"Invalid change_type '{change_type}'")
        clauses.append({"change_type": change_type})
    if priority:
        if priority not in INCIDENT_PRIORITIES:
            raise ChangeError(f"Invalid priority '{priority}'")
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
                    {"change_id": rx},
                    {"number_display": rx},
                    {"justification": rx},
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
        "change_id",
        "change_type",
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


def create_change(
    payload: ChangeCreate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if payload.status not in CHANGE_STATUSES:
        raise ChangeError(f"Invalid status '{payload.status}'")
    if payload.change_type not in CHANGE_TYPES:
        raise ChangeError(f"Invalid change_type '{payload.change_type}'")
    if payload.priority not in INCIDENT_PRIORITIES:
        raise ChangeError(f"Invalid priority '{payload.priority}'")

    try:
        ci_links = resolve_ci_links(payload.ci_links, tenant_id=tid)
    except CmdbLinkError as exc:
        raise ChangeError(exc.message, status_code=exc.status_code) from exc

    now = _now()
    number = _next_number(tenant_id=tid)
    change_id = _new_change_id()
    who = _actor_fields(actor)
    doc: dict[str, Any] = {
        "change_id": change_id,
        "number": number,
        "number_display": f"CHG-{number:05d}",
        "title": payload.title.strip(),
        "description": (payload.description or "").strip() or None,
        "justification": (payload.justification or "").strip() or None,
        "status": payload.status,
        "change_type": payload.change_type,
        "risk": payload.risk,
        "impact": payload.impact,
        "urgency": (payload.urgency or "").strip() or None,
        "priority": payload.priority,
        "category": (payload.category or "").strip() or None,
        "subcategory": (payload.subcategory or "").strip() or None,
        "assignment_group": payload.assignment_group,
        "assignee_user_id": payload.assignee_user_id,
        "service_tier": (payload.service_tier or "").strip() or None,
        "customer_class": (payload.customer_class or "").strip() or None,
        "ci_tier": (payload.ci_tier or "").strip() or None,
        "ci_criticality": (payload.ci_criticality or "").strip() or None,
        "planned_start": payload.planned_start,
        "planned_end": payload.planned_end,
        "actual_start": None,
        "actual_end": None,
        "implementation_plan": (payload.implementation_plan or "").strip() or None,
        "test_plan": (payload.test_plan or "").strip() or None,
        "backout_plan": (payload.backout_plan or "").strip() or None,
        "cab_required": bool(payload.cab_required),
        "ci_links": ci_links,
        "related_incident_ids": _clean_id_list(payload.related_incident_ids),
        "related_problem_ids": _clean_id_list(payload.related_problem_ids),
        "sla_tracking_ids": [],
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
        ticket_type="change",
        ticket_id=change_id,
        activity_type="created",
        message=f"Change created ({doc['number_display']})",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        to_value=payload.status,
    )
    from . import sla as sla_service

    sla_service.notify_ticket_created(
        tenant_id=tid,
        ticket_type="change",
        ticket_id=change_id,
        priority=payload.priority,
        status=payload.status,
        actor=actor,
    )
    from . import workflow_triggers as workflow_triggers_service

    workflow_triggers_service.fire_on_create(
        ticket_type="change",
        ticket_id=change_id,
        tenant_id=tid,
        actor=actor,
    )
    refreshed = _coll().find_one({"tenant_id": tid, "change_id": change_id})
    return serialize_document(refreshed or doc)  # type: ignore[return-value]


def update_change(
    change_id: str,
    payload: ChangeUpdate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "change_id": change_id})
    if existing is None:
        raise ChangeError(f"Change '{change_id}' not found", status_code=404)

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return serialize_document(existing)  # type: ignore[return-value]

    if "priority" in updates and updates["priority"] not in INCIDENT_PRIORITIES:
        raise ChangeError(f"Invalid priority '{updates['priority']}'")
    if "change_type" in updates and updates["change_type"] not in CHANGE_TYPES:
        raise ChangeError(f"Invalid change_type '{updates['change_type']}'")
    if "related_incident_ids" in updates:
        updates["related_incident_ids"] = _clean_id_list(updates["related_incident_ids"])
    if "related_problem_ids" in updates:
        updates["related_problem_ids"] = _clean_id_list(updates["related_problem_ids"])

    who = _actor_fields(actor)
    updates["updated_at"] = _now()
    updates["updated_by"] = who["username"]

    old_assignee = existing.get("assignee_user_id")
    new_assignee = updates.get("assignee_user_id", old_assignee)
    unset_fields = payload.model_dump(exclude_unset=True)

    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "change_id": change_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise ChangeError(f"Change '{change_id}' not found", status_code=404)

    if "assignee_user_id" in unset_fields and old_assignee != new_assignee:
        activities_service.append_activity(
            tenant_id=tid,
            ticket_type="change",
            ticket_id=change_id,
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
            ticket_type="change",
            ticket_id=change_id,
            assignee_user_id=new_assignee,
            number_display=doc.get("number_display"),
            actor=actor,
        )
    else:
        activities_service.append_activity(
            tenant_id=tid,
            ticket_type="change",
            ticket_id=change_id,
            activity_type="system",
            message="Change details updated",
            actor_user_id=who["user_id"],
            actor_username=who["username"],
        )
    from . import sla as sla_service

    if sla_service.match_context_changed(existing, doc):
        sla_service.notify_context_changed(
            tenant_id=tid,
            ticket_type="change",
            ticket_id=change_id,
            priority=str(doc.get("priority") or existing.get("priority") or "p3"),
            status=str(doc.get("status") or "draft"),
            actor=actor,
            ticket=doc,
            reason="context_change",
        )
        refreshed = _coll().find_one({"tenant_id": tid, "change_id": change_id})
        if refreshed is not None:
            doc = refreshed
    return serialize_document(doc)  # type: ignore[return-value]


def transition_change(
    change_id: str,
    payload: ChangeTransition,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "change_id": change_id})
    if existing is None:
        raise ChangeError(f"Change '{change_id}' not found", status_code=404)

    current = str(existing.get("status") or "")
    target = payload.status
    if target not in CHANGE_STATUSES:
        raise ChangeError(f"Invalid status '{target}'")
    allowed = CHANGE_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ChangeError(
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
    if target == "implementing" and not existing.get("actual_start"):
        updates["actual_start"] = now.isoformat()
    if target == "closed":
        updates["closed_at"] = now
        if not existing.get("actual_end"):
            updates["actual_end"] = now.isoformat()

    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "change_id": change_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise ChangeError(f"Change '{change_id}' not found", status_code=404)

    msg = payload.comment or f"Status changed from {current} to {target}"
    activities_service.append_activity(
        tenant_id=tid,
        ticket_type="change",
        ticket_id=change_id,
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
        ticket_type="change",
        ticket_id=change_id,
        from_status=current,
        to_status=target,
        priority=str(doc.get("priority") or "p3"),
        actor=actor,
    )
    notifications_service.notify_status_change(
        tenant_id=tid,
        ticket_type="change",
        ticket_id=change_id,
        from_status=current,
        to_status=target,
        assignee_user_id=doc.get("assignee_user_id"),
        number_display=doc.get("number_display"),
        actor=actor,
    )
    from . import workflow_triggers as workflow_triggers_service

    workflow_triggers_service.fire_on_status(
        ticket_type="change",
        ticket_id=change_id,
        from_status=current,
        to_status=target,
        tenant_id=tid,
        actor=actor,
    )
    return serialize_document(doc)  # type: ignore[return-value]


def add_ci_link(
    change_id: str,
    *,
    component_id: str,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "change_id": change_id})
    if existing is None:
        raise ChangeError(f"Change '{change_id}' not found", status_code=404)

    try:
        link = resolve_component_link(component_id, tenant_id=tid)
    except CmdbLinkError as exc:
        raise ChangeError(exc.message, status_code=exc.status_code) from exc

    links = list(existing.get("ci_links") or [])
    if any(str(x.get("component_id")) == link["component_id"] for x in links):
        return serialize_document(existing)  # type: ignore[return-value]

    links.append(link)
    who = _actor_fields(actor)
    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "change_id": change_id},
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
        ticket_type="change",
        ticket_id=change_id,
        activity_type="ci_link",
        message=f"Linked CI {link['component_id']}",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        to_value=link["component_id"],
    )
    return serialize_document(doc)  # type: ignore[return-value]


def remove_ci_link(
    change_id: str,
    *,
    component_id: str,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "change_id": change_id})
    if existing is None:
        raise ChangeError(f"Change '{change_id}' not found", status_code=404)

    cid = component_id.strip()
    links = [x for x in (existing.get("ci_links") or []) if str(x.get("component_id")) != cid]
    if len(links) == len(existing.get("ci_links") or []):
        raise ChangeError(
            f"CI link '{cid}' not found on change",
            status_code=404,
        )

    who = _actor_fields(actor)
    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "change_id": change_id},
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
        ticket_type="change",
        ticket_id=change_id,
        activity_type="ci_link",
        message=f"Unlinked CI {cid}",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        from_value=cid,
    )
    return serialize_document(doc)  # type: ignore[return-value]
