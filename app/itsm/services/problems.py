"""Problem Management service — ITSM DB only; CI validation via CMDB services."""

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
from ..models.common import PROBLEM_PRIORITIES, PROBLEM_STATUSES, PROBLEM_TRANSITIONS
from ..models.problems import ProblemCreate, ProblemTransition, ProblemUpdate
from . import activities as activities_service
from .cmdb_links import CmdbLinkError, resolve_ci_links, resolve_component_link
from .indexes import COUNTERS, PROBLEMS, ensure_itsm_indexes


class ProblemError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[PROBLEMS]


def _counters() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[COUNTERS]


def _new_problem_id() -> str:
    return f"PRB-{uuid.uuid4().hex[:10].upper()}"


def _next_number(*, tenant_id: str) -> int:
    tid = require_tenant_id(tenant_id)
    doc = _counters().find_one_and_update(
        {"tenant_id": tid, "counter_key": "problem"},
        {"$inc": {"value": 1}, "$setOnInsert": {"tenant_id": tid, "counter_key": "problem"}},
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


def get_problem(problem_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one({"tenant_id": tid, "problem_id": problem_id})
    return serialize_document(doc)


def list_problems(
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
        if status not in PROBLEM_STATUSES:
            raise ProblemError(f"Invalid status '{status}'")
        clauses.append({"status": status})
    if priority:
        if priority not in PROBLEM_PRIORITIES:
            raise ProblemError(f"Invalid priority '{priority}'")
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
                    {"problem_id": rx},
                    {"number_display": rx},
                    {"category": rx},
                    {"root_cause": rx},
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
        "problem_id",
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


def create_problem(
    payload: ProblemCreate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if payload.status not in PROBLEM_STATUSES:
        raise ProblemError(f"Invalid status '{payload.status}'")
    if payload.priority not in PROBLEM_PRIORITIES:
        raise ProblemError(f"Invalid priority '{payload.priority}'")

    try:
        ci_links = resolve_ci_links(payload.ci_links, tenant_id=tid)
    except CmdbLinkError as exc:
        raise ProblemError(exc.message, status_code=exc.status_code) from exc

    now = _now()
    number = _next_number(tenant_id=tid)
    problem_id = _new_problem_id()
    who = _actor_fields(actor)
    status = payload.status
    if payload.known_error and status == "new":
        status = "known_error"
    doc: dict[str, Any] = {
        "problem_id": problem_id,
        "number": number,
        "number_display": f"PRB-{number:05d}",
        "title": payload.title.strip(),
        "description": (payload.description or "").strip() or None,
        "status": status,
        "priority": payload.priority,
        "category": payload.category,
        "subcategory": payload.subcategory,
        "urgency": (payload.urgency or "").strip() or None,
        "impact": (payload.impact or "").strip() or None,
        "assignment_group": payload.assignment_group,
        "assignee_user_id": payload.assignee_user_id,
        "service_tier": (payload.service_tier or "").strip() or None,
        "customer_class": (payload.customer_class or "").strip() or None,
        "ci_tier": (payload.ci_tier or "").strip() or None,
        "ci_criticality": (payload.ci_criticality or "").strip() or None,
        "root_cause": (payload.root_cause or "").strip() or None,
        "workaround": (payload.workaround or "").strip() or None,
        "known_error": bool(payload.known_error) or status == "known_error",
        "ci_links": ci_links,
        "related_incident_ids": _clean_id_list(payload.related_incident_ids),
        "change_id": (payload.change_id or "").strip() or None,
        "sla_tracking_ids": [],
        "resolved_at": now if status == "resolved" else None,
        "closed_at": now if status == "closed" else None,
        "created_at": now,
        "updated_at": now,
        "created_by": who["username"],
        "updated_by": who["username"],
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _coll().insert_one(doc)

    activities_service.append_activity(
        tenant_id=tid,
        ticket_type="problem",
        ticket_id=problem_id,
        activity_type="created",
        message=f"Problem created ({doc['number_display']})",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        to_value=status,
    )
    from . import sla as sla_service

    sla_service.notify_ticket_created(
        tenant_id=tid,
        ticket_type="problem",
        ticket_id=problem_id,
        priority=payload.priority,
        status=status,
        actor=actor,
    )
    refreshed = _coll().find_one({"tenant_id": tid, "problem_id": problem_id})
    return serialize_document(refreshed or doc)  # type: ignore[return-value]


def update_problem(
    problem_id: str,
    payload: ProblemUpdate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "problem_id": problem_id})
    if existing is None:
        raise ProblemError(f"Problem '{problem_id}' not found", status_code=404)

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return serialize_document(existing)  # type: ignore[return-value]

    if "priority" in updates and updates["priority"] not in PROBLEM_PRIORITIES:
        raise ProblemError(f"Invalid priority '{updates['priority']}'")
    if "related_incident_ids" in updates:
        updates["related_incident_ids"] = _clean_id_list(updates["related_incident_ids"])
    if "change_id" in updates and updates["change_id"] is not None:
        updates["change_id"] = str(updates["change_id"]).strip() or None
    if updates.get("known_error") is True and existing.get("status") in {
        "new",
        "under_investigation",
    }:
        # Flag alone does not force status; leave status unless already known_error.
        pass

    who = _actor_fields(actor)
    updates["updated_at"] = _now()
    updates["updated_by"] = who["username"]

    old_assignee = existing.get("assignee_user_id")
    new_assignee = updates.get("assignee_user_id", old_assignee)
    unset_fields = payload.model_dump(exclude_unset=True)

    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "problem_id": problem_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise ProblemError(f"Problem '{problem_id}' not found", status_code=404)

    if "assignee_user_id" in unset_fields and old_assignee != new_assignee:
        activities_service.append_activity(
            tenant_id=tid,
            ticket_type="problem",
            ticket_id=problem_id,
            activity_type="assignment",
            message="Assignee updated",
            actor_user_id=who["user_id"],
            actor_username=who["username"],
            from_value=old_assignee,
            to_value=new_assignee,
        )
    else:
        activities_service.append_activity(
            tenant_id=tid,
            ticket_type="problem",
            ticket_id=problem_id,
            activity_type="system",
            message="Problem details updated",
            actor_user_id=who["user_id"],
            actor_username=who["username"],
        )
    from . import sla as sla_service

    if sla_service.match_context_changed(existing, doc):
        sla_service.notify_context_changed(
            tenant_id=tid,
            ticket_type="problem",
            ticket_id=problem_id,
            priority=str(doc.get("priority") or existing.get("priority") or "p3"),
            status=str(doc.get("status") or "new"),
            actor=actor,
            ticket=doc,
            reason="context_change",
        )
        refreshed = _coll().find_one({"tenant_id": tid, "problem_id": problem_id})
        if refreshed is not None:
            doc = refreshed
    return serialize_document(doc)  # type: ignore[return-value]


def transition_problem(
    problem_id: str,
    payload: ProblemTransition,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "problem_id": problem_id})
    if existing is None:
        raise ProblemError(f"Problem '{problem_id}' not found", status_code=404)

    current = str(existing.get("status") or "")
    target = payload.status
    if target not in PROBLEM_STATUSES:
        raise ProblemError(f"Invalid status '{target}'")
    allowed = PROBLEM_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ProblemError(
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
    if payload.root_cause is not None:
        updates["root_cause"] = payload.root_cause
    if payload.workaround is not None:
        updates["workaround"] = payload.workaround
    if target == "known_error":
        updates["known_error"] = True
    if target == "resolved":
        updates["resolved_at"] = now
    if target == "closed":
        updates["closed_at"] = now
        if not existing.get("resolved_at"):
            updates["resolved_at"] = now

    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "problem_id": problem_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise ProblemError(f"Problem '{problem_id}' not found", status_code=404)

    msg = payload.comment or f"Status changed from {current} to {target}"
    activities_service.append_activity(
        tenant_id=tid,
        ticket_type="problem",
        ticket_id=problem_id,
        activity_type="status_change",
        message=msg,
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        from_value=current,
        to_value=target,
    )
    from . import sla as sla_service

    sla_service.notify_status_changed(
        tenant_id=tid,
        ticket_type="problem",
        ticket_id=problem_id,
        from_status=current,
        to_status=target,
        priority=str(doc.get("priority") or "p3"),
        actor=actor,
    )
    return serialize_document(doc)  # type: ignore[return-value]


def add_ci_link(
    problem_id: str,
    *,
    component_id: str,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "problem_id": problem_id})
    if existing is None:
        raise ProblemError(f"Problem '{problem_id}' not found", status_code=404)

    try:
        link = resolve_component_link(component_id, tenant_id=tid)
    except CmdbLinkError as exc:
        raise ProblemError(exc.message, status_code=exc.status_code) from exc

    links = list(existing.get("ci_links") or [])
    if any(str(x.get("component_id")) == link["component_id"] for x in links):
        return serialize_document(existing)  # type: ignore[return-value]

    links.append(link)
    who = _actor_fields(actor)
    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "problem_id": problem_id},
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
        ticket_type="problem",
        ticket_id=problem_id,
        activity_type="ci_link",
        message=f"Linked CI {link['component_id']}",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        to_value=link["component_id"],
    )
    return serialize_document(doc)  # type: ignore[return-value]


def remove_ci_link(
    problem_id: str,
    *,
    component_id: str,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "problem_id": problem_id})
    if existing is None:
        raise ProblemError(f"Problem '{problem_id}' not found", status_code=404)

    cid = component_id.strip()
    links = [x for x in (existing.get("ci_links") or []) if str(x.get("component_id")) != cid]
    if len(links) == len(existing.get("ci_links") or []):
        raise ProblemError(
            f"CI link '{cid}' not found on problem",
            status_code=404,
        )

    who = _actor_fields(actor)
    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "problem_id": problem_id},
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
        ticket_type="problem",
        ticket_id=problem_id,
        activity_type="ci_link",
        message=f"Unlinked CI {cid}",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        from_value=cid,
    )
    return serialize_document(doc)  # type: ignore[return-value]
