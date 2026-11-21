"""SLA policies + tracking — ITSM DB only; auto-attach on ticket events."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from ..models.common import TICKET_TYPES
from ..models.sla import (
    MATCH_WEIGHTS,
    SLA_METRICS,
    SLA_TRACKING_STATUSES,
    SlaPolicyCreate,
    SlaPolicyUpdate,
)
from . import activities as activities_service
from .indexes import SLA_POLICIES, SLA_TRACKING, ensure_itsm_indexes
from .sla_clock import (
    business_seconds_between,
    compute_due_after_resume,
    compute_due_at,
    is_business_hours_calendar,
)

# Ticket fields that affect which policy wins (reattach when any change).
_MATCH_CONTEXT_FIELDS: frozenset[str] = frozenset(
    {
        "priority",
        "service_tier",
        "customer_class",
        "category",
        "subcategory",
        "assignment_group",
        "urgency",
        "impact",
        "ci_tier",
        "ci_criticality",
    }
)

# Terminal statuses complete the resolution clock (and cancel leftover response clocks).
_TERMINAL_BY_TYPE: dict[str, frozenset[str]] = {
    "incident": frozenset({"resolved", "closed", "cancelled"}),
    "change": frozenset({"closed", "rejected", "cancelled"}),
    "problem": frozenset({"resolved", "closed", "cancelled"}),
}

_INITIAL_BY_TYPE: dict[str, frozenset[str]] = {
    "incident": frozenset({"new"}),
    "change": frozenset({"draft"}),
    "problem": frozenset({"new"}),
}

_DEFAULT_PAUSE: dict[str, list[str]] = {
    "incident": ["on_hold"],
    "change": [],
    "problem": [],
}


class SlaError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _policies() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[SLA_POLICIES]


def _tracking() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[SLA_TRACKING]


def _new_policy_id() -> str:
    return f"SLA-{uuid.uuid4().hex[:10].upper()}"


def _new_tracking_id() -> str:
    return f"SLT-{uuid.uuid4().hex[:10].upper()}"


def _actor_fields(actor: dict[str, Any] | None) -> dict[str, str | None]:
    actor = actor or {}
    return {
        "user_id": actor.get("user_id") or actor.get("username"),
        "username": actor.get("username") or actor.get("user_id"),
    }


def _targets_to_docs(targets: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for target in targets:
        data = target.model_dump() if hasattr(target, "model_dump") else dict(target)
        out.append(
            {
                "metric": data["metric"],
                "priority_targets": [
                    {"priority": row["priority"], "minutes": int(row["minutes"])}
                    for row in data["priority_targets"]
                ],
            }
        )
    return out


def _minutes_for_priority(target: dict[str, Any], priority: str) -> int | None:
    for row in target.get("priority_targets") or []:
        if row.get("priority") == priority:
            return int(row["minutes"])
    return None


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.lower() if text else None


def _match_doc(match: Any) -> dict[str, Any]:
    if match is None:
        return {}
    if hasattr(match, "model_dump"):
        data = match.model_dump(exclude_none=True)
    elif isinstance(match, dict):
        data = {k: v for k, v in match.items() if v is not None and v != ""}
    else:
        data = {}
    # Drop empty lists.
    if not data.get("priorities"):
        data.pop("priorities", None)
    return data


def build_ticket_context(ticket: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize ticket (+ CI snapshot) fields used for SLA matching."""
    ticket = ticket or {}
    ci_links = ticket.get("ci_links") or []
    ci_tiers: list[str] = []
    ci_crits: list[str] = []
    for link in ci_links:
        if not isinstance(link, dict):
            continue
        t = _norm(link.get("ci_tier"))
        c = _norm(link.get("criticality"))
        if t:
            ci_tiers.append(t)
        if c:
            ci_crits.append(c)
    ticket_ci_tier = _norm(ticket.get("ci_tier"))
    ticket_ci_crit = _norm(ticket.get("ci_criticality"))
    if ticket_ci_tier:
        ci_tiers.insert(0, ticket_ci_tier)
    if ticket_ci_crit:
        ci_crits.insert(0, ticket_ci_crit)
    return {
        "priority": _norm(ticket.get("priority")),
        "service_tier": _norm(ticket.get("service_tier")),
        "customer_class": _norm(ticket.get("customer_class")),
        "category": _norm(ticket.get("category")),
        "subcategory": _norm(ticket.get("subcategory")),
        "assignment_group": _norm(ticket.get("assignment_group")),
        "urgency": _norm(ticket.get("urgency")),
        "impact": _norm(ticket.get("impact")),
        "ci_tier": ticket_ci_tier,
        "ci_criticality": ticket_ci_crit,
        "ci_tiers": ci_tiers,
        "ci_criticalities": ci_crits,
    }


def evaluate_policy_match(
    policy: dict[str, Any],
    context: dict[str, Any],
) -> tuple[bool, int, dict[str, Any]]:
    """Return (matches, specificity_score, matched_fields).

    Missing / empty match fields are wildcards. Most-specific wins among matches.
    """
    match = policy.get("match") or {}
    if hasattr(match, "model_dump"):
        match = match.model_dump(exclude_none=True)
    matched: dict[str, Any] = {}
    score = 0

    def require_eq(field: str, ticket_value: str | None) -> bool:
        nonlocal score
        expected = _norm(match.get(field)) if isinstance(match, dict) else None
        if not expected:
            return True  # wildcard
        if ticket_value == expected:
            matched[field] = ticket_value
            score += MATCH_WEIGHTS.get(field, 10)
            return True
        return False

    if not isinstance(match, dict):
        match = {}

    checks = [
        ("service_tier", context.get("service_tier")),
        ("customer_class", context.get("customer_class")),
        ("category", context.get("category")),
        ("subcategory", context.get("subcategory")),
        ("assignment_group", context.get("assignment_group")),
        ("urgency", context.get("urgency")),
        ("impact", context.get("impact")),
    ]
    for field, value in checks:
        if not require_eq(field, value):
            return False, 0, {}

    # CI criticality: ticket field OR any ci_links snapshot.
    expected_crit = _norm(match.get("ci_criticality"))
    if expected_crit:
        pool = set(context.get("ci_criticalities") or [])
        if context.get("ci_criticality"):
            pool.add(context["ci_criticality"])
        if expected_crit not in pool:
            return False, 0, {}
        matched["ci_criticality"] = expected_crit
        score += MATCH_WEIGHTS.get("ci_criticality", 10)

    expected_ci_tier = _norm(match.get("ci_tier"))
    if expected_ci_tier:
        pool = set(context.get("ci_tiers") or [])
        if context.get("ci_tier"):
            pool.add(context["ci_tier"])
        if expected_ci_tier not in pool:
            return False, 0, {}
        matched["ci_tier"] = expected_ci_tier
        score += MATCH_WEIGHTS.get("ci_tier", 10)

    priorities = match.get("priorities") or []
    if priorities:
        allowed = {_norm(p) for p in priorities if _norm(p)}
        ticket_priority = context.get("priority")
        if ticket_priority not in allowed:
            return False, 0, {}
        matched["priorities"] = sorted(allowed)
        matched["priority"] = ticket_priority
        score += MATCH_WEIGHTS.get("priorities", 10)

    return True, score, matched


def select_winning_policy(
    policies: list[dict[str, Any]],
    context: dict[str, Any],
) -> tuple[dict[str, Any] | None, int, dict[str, Any]]:
    """Pick the most specific matching policy.

    Sort key: specificity score DESC, priority_order ASC, updated_at DESC.
    """
    candidates: list[tuple[int, int, Any, dict[str, Any], dict[str, Any]]] = []
    for policy in policies:
        ok, score, matched = evaluate_policy_match(policy, context)
        if not ok:
            continue
        order = int(policy.get("priority_order") if policy.get("priority_order") is not None else 100)
        candidates.append((score, order, policy.get("updated_at"), policy, matched))

    if not candidates:
        return None, 0, {}

    candidates.sort(
        key=lambda row: (-row[0], row[1], row[2] is None, row[2]),
    )
    best = candidates[0]
    return best[3], best[0], best[4]


def _ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def ensure_ticket_exists(ticket_type: str, ticket_id: str, *, tenant_id: str) -> dict[str, Any]:
    if ticket_type not in TICKET_TYPES:
        raise SlaError(f"Invalid ticket_type '{ticket_type}'")
    from . import changes as changes_service
    from . import incidents as incidents_service
    from . import problems as problems_service

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
        raise SlaError(f"{label} '{ticket_id}' not found", status_code=404)
    return doc


def _ticket_collection_name(ticket_type: str) -> str:
    return {
        "incident": "itsm_incidents",
        "change": "itsm_changes",
        "problem": "itsm_problems",
    }[ticket_type]


def _ticket_id_field(ticket_type: str) -> str:
    return {
        "incident": "incident_id",
        "change": "change_id",
        "problem": "problem_id",
    }[ticket_type]


def _append_ticket_tracking_ids(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    tracking_ids: list[str],
) -> None:
    if not tracking_ids:
        return
    coll = require_itsm_database()[_ticket_collection_name(ticket_type)]
    coll.update_one(
        {"tenant_id": tenant_id, _ticket_id_field(ticket_type): ticket_id},
        {
            "$addToSet": {"sla_tracking_ids": {"$each": tracking_ids}},
            "$set": {"updated_at": _now()},
        },
    )


def _refresh_breach_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """If a running clock is past due_at, persist breached status."""
    if doc.get("status") != "running":
        return doc
    due = _ensure_aware(doc.get("due_at"))
    if due is None:
        return doc
    now = _now()
    if due > now:
        return doc
    tid = doc.get("tenant_id")
    tracking_id = doc.get("tracking_id")
    if not tid or not tracking_id:
        doc["status"] = "breached"
        doc["breached_at"] = due
        return doc
    updated = _tracking().find_one_and_update(
        {
            "tenant_id": tid,
            "tracking_id": tracking_id,
            "status": "running",
        },
        {
            "$set": {
                "status": "breached",
                "breached_at": due,
                "updated_at": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    result = updated or doc
    if updated is not None and updated.get("status") == "breached":
        try:
            from . import notifications as notifications_service

            assignee, number_display = notifications_service.lookup_ticket_assignee(
                tenant_id=str(tid),
                ticket_type=str(updated.get("ticket_type") or ""),
                ticket_id=str(updated.get("ticket_id") or ""),
            )
            notifications_service.notify_sla_breach(
                tenant_id=str(tid),
                ticket_type=str(updated.get("ticket_type") or ""),
                ticket_id=str(updated.get("ticket_id") or ""),
                tracking_id=str(tracking_id),
                metric=str(updated.get("metric") or "SLA"),
                assignee_user_id=assignee,
                number_display=number_display,
            )
        except Exception:  # noqa: BLE001 — breach refresh must not fail
            pass
    return result


def get_policy(policy_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _policies().find_one({"tenant_id": tid, "policy_id": policy_id})
    return serialize_document(doc)


def list_policies(
    *,
    tenant_id: str,
    q: str | None = None,
    active: bool | None = None,
    applies_to: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    clauses: list[dict[str, Any]] = []
    if active is not None:
        clauses.append({"active": bool(active)})
    if applies_to:
        if applies_to not in TICKET_TYPES:
            raise SlaError(f"Invalid applies_to '{applies_to}'")
        clauses.append({"applies_to": applies_to})
    if q and q.strip():
        term = q.strip()
        clauses.append(
            {
                "$or": [
                    {"name": {"$regex": term, "$options": "i"}},
                    {"policy_id": {"$regex": term, "$options": "i"}},
                    {"description": {"$regex": term, "$options": "i"}},
                ]
            }
        )

    query: dict[str, Any] = {"tenant_id": tid}
    if clauses:
        query = merge_tenant_filter({"$and": clauses}, tid)

    allowed_sort = {"updated_at", "created_at", "name", "active", "applies_to"}
    if sort_by not in allowed_sort:
        sort_by = "updated_at"
    direction = DESCENDING if str(sort_dir).lower() != "asc" else ASCENDING

    coll = _policies()
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


def create_policy(
    payload: SlaPolicyCreate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    who = _actor_fields(actor)
    now = _now()
    policy_id = _new_policy_id()
    pause = list(payload.pause_on_statuses)
    if not pause:
        pause = list(_DEFAULT_PAUSE.get(payload.applies_to, []))
    doc: dict[str, Any] = {
        "policy_id": policy_id,
        "name": payload.name.strip(),
        "description": (payload.description or "").strip() or None,
        "active": bool(payload.active),
        "applies_to": payload.applies_to,
        "priority_order": int(payload.priority_order),
        "match": _match_doc(payload.match),
        "targets": _targets_to_docs(payload.targets),
        "pause_on_statuses": pause,
        "calendar": payload.calendar.model_dump(),
        "created_at": now,
        "updated_at": now,
        "created_by": who["username"],
        "updated_by": who["username"],
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _policies().insert_one(doc)
    return serialize_document(doc)  # type: ignore[return-value]


def update_policy(
    policy_id: str,
    payload: SlaPolicyUpdate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _policies().find_one({"tenant_id": tid, "policy_id": policy_id})
    if existing is None:
        raise SlaError(f"SLA policy '{policy_id}' not found", status_code=404)

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return serialize_document(existing)  # type: ignore[return-value]
    if "name" in updates and updates["name"] is not None:
        updates["name"] = updates["name"].strip()
    if "description" in updates and updates["description"] is not None:
        updates["description"] = updates["description"].strip() or None
    if "match" in updates:
        updates["match"] = _match_doc(payload.match)
    if "targets" in updates and updates["targets"] is not None:
        updates["targets"] = _targets_to_docs(payload.targets or [])
    if "calendar" in updates and updates["calendar"] is not None:
        updates["calendar"] = (
            payload.calendar.model_dump() if payload.calendar else updates["calendar"]
        )

    who = _actor_fields(actor)
    updates["updated_at"] = _now()
    updates["updated_by"] = who["username"]

    doc = _policies().find_one_and_update(
        {"tenant_id": tid, "policy_id": policy_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise SlaError(f"SLA policy '{policy_id}' not found", status_code=404)
    return serialize_document(doc)  # type: ignore[return-value]


def get_tracking(tracking_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _tracking().find_one({"tenant_id": tid, "tracking_id": tracking_id})
    if doc is None:
        return None
    doc = _refresh_breach_doc(doc)
    return serialize_document(doc)


def list_tracking(
    *,
    tenant_id: str,
    q: str | None = None,
    status: str | None = None,
    ticket_type: str | None = None,
    ticket_id: str | None = None,
    policy_id: str | None = None,
    metric: str | None = None,
    overdue: bool | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "due_at",
    sort_dir: str = "asc",
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    clauses: list[dict[str, Any]] = []
    if status:
        if status not in SLA_TRACKING_STATUSES:
            raise SlaError(f"Invalid status '{status}'")
        clauses.append({"status": status})
    if ticket_type:
        if ticket_type not in TICKET_TYPES:
            raise SlaError(f"Invalid ticket_type '{ticket_type}'")
        clauses.append({"ticket_type": ticket_type})
    if ticket_id:
        clauses.append({"ticket_id": ticket_id.strip()})
    if policy_id:
        clauses.append({"policy_id": policy_id.strip()})
    if metric:
        if metric not in SLA_METRICS:
            raise SlaError(f"Invalid metric '{metric}'")
        clauses.append({"metric": metric})
    if overdue:
        now = _now()
        clauses.append(
            {
                "$or": [
                    {"status": "breached"},
                    {
                        "status": {"$in": ["running", "paused"]},
                        "due_at": {"$lt": now},
                    },
                ]
            }
        )
    if q and q.strip():
        term = q.strip()
        clauses.append(
            {
                "$or": [
                    {"tracking_id": {"$regex": term, "$options": "i"}},
                    {"policy_id": {"$regex": term, "$options": "i"}},
                    {"policy_name_snapshot": {"$regex": term, "$options": "i"}},
                    {"ticket_id": {"$regex": term, "$options": "i"}},
                ]
            }
        )

    query: dict[str, Any] = {"tenant_id": tid}
    if clauses:
        query = merge_tenant_filter({"$and": clauses}, tid)

    allowed_sort = {
        "due_at",
        "updated_at",
        "created_at",
        "status",
        "metric",
        "breached_at",
    }
    if sort_by not in allowed_sort:
        sort_by = "due_at"
    direction = DESCENDING if str(sort_dir).lower() != "asc" else ASCENDING

    coll = _tracking()
    # Best-effort breach refresh for overdue running clocks in this page filter.
    if overdue or status in (None, "running", "breached"):
        now = _now()
        coll.update_many(
            {
                "tenant_id": tid,
                "status": "running",
                "due_at": {"$lt": now},
            },
            {"$set": {"status": "breached", "breached_at": now, "updated_at": now}},
        )

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


def summary_for_ticket(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
) -> dict[str, Any]:
    """Compact SLA summary for ticket detail badges."""
    tid = require_tenant_id(tenant_id)
    if ticket_type not in TICKET_TYPES:
        raise SlaError(f"Invalid ticket_type '{ticket_type}'")
    # Refresh breaches for this ticket.
    now = _now()
    _tracking().update_many(
        {
            "tenant_id": tid,
            "ticket_type": ticket_type,
            "ticket_id": ticket_id,
            "status": "running",
            "due_at": {"$lt": now},
        },
        {"$set": {"status": "breached", "breached_at": now, "updated_at": now}},
    )
    rows = list(
        _tracking().find(
            {
                "tenant_id": tid,
                "ticket_type": ticket_type,
                "ticket_id": ticket_id,
            }
        )
    )
    items = [serialize_document(r) for r in rows]
    counts = {"running": 0, "paused": 0, "met": 0, "breached": 0, "cancelled": 0}
    for row in items:
        st = str(row.get("status") or "")
        if st in counts:
            counts[st] += 1
    worst = "none"
    if counts["breached"]:
        worst = "breached"
    elif counts["paused"]:
        worst = "paused"
    elif counts["running"]:
        worst = "running"
    elif counts["met"]:
        worst = "met"
    return {
        "ticket_type": ticket_type,
        "ticket_id": ticket_id,
        "tenant_id": tid,
        "worst_status": worst,
        "counts": counts,
        "items": items,
    }


def _create_tracking_rows(
    *,
    tenant_id: str,
    policy: dict[str, Any],
    ticket_type: str,
    ticket_id: str,
    priority: str,
    status: str,
    actor: dict[str, Any] | None,
    matched_fields: dict[str, Any] | None = None,
    match_score: int = 0,
) -> list[dict[str, Any]]:
    who = _actor_fields(actor)
    now = _now()
    pause_statuses = set(policy.get("pause_on_statuses") or [])
    initial_paused = status in pause_statuses
    created: list[dict[str, Any]] = []
    tracking_ids: list[str] = []
    matched_fields = matched_fields or {}
    why = (
        ", ".join(f"{k}={v}" for k, v in matched_fields.items())
        if matched_fields
        else "wildcard (default policy)"
    )

    calendar = dict(policy.get("calendar") or {})
    for target in policy.get("targets") or []:
        metric = target.get("metric")
        if metric not in SLA_METRICS:
            continue
        minutes = _minutes_for_priority(target, priority)
        if minutes is None:
            continue
        tracking_id = _new_tracking_id()
        due_at = compute_due_at(
            started_at=now, target_minutes=minutes, calendar=calendar
        )
        doc: dict[str, Any] = {
            "tracking_id": tracking_id,
            "policy_id": policy["policy_id"],
            "policy_name_snapshot": policy.get("name"),
            "ticket_type": ticket_type,
            "ticket_id": ticket_id,
            "metric": metric,
            "priority_at_start": priority,
            "target_minutes": minutes,
            "started_at": now,
            "due_at": due_at,
            "paused_at": now if initial_paused else None,
            "paused_total_seconds": 0,
            "elapsed_business_seconds": 0,
            "running_since": None if initial_paused else now,
            "calendar_snapshot": calendar,
            "breached_at": None,
            "completed_at": None,
            "status": "paused" if initial_paused else "running",
            "match_score": int(match_score),
            "matched_fields": matched_fields,
            "match_reason": why,
            "policy_priority_order": int(
                policy.get("priority_order")
                if policy.get("priority_order") is not None
                else 100
            ),
            "created_at": now,
            "updated_at": now,
            "created_by": who["username"],
            "updated_by": who["username"],
        }
        stamp_tenant_id(doc, tenant_id=tenant_id)
        _tracking().insert_one(doc)
        created.append(serialize_document(doc))  # type: ignore[arg-type]
        tracking_ids.append(tracking_id)

    _append_ticket_tracking_ids(
        tenant_id=tenant_id,
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        tracking_ids=tracking_ids,
    )
    if created:
        activities_service.append_activity(
            tenant_id=tenant_id,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            activity_type="sla",
            message=(
                f"SLA attached: {policy.get('name')} ({policy.get('policy_id')}) "
                f"· score={match_score} · {why} · {len(created)} metric(s)"
            ),
            actor_user_id=who["user_id"],
            actor_username=who["username"],
            to_value=policy.get("policy_id"),
        )
    return created  # type: ignore[return-value]


def attach_matching_policies(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    priority: str,
    status: str,
    actor: dict[str, Any] | None = None,
    ticket: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Attach the single most-specific matching active policy (tenant-scoped).

    Match algorithm (documented):
    1. Load active policies where ``applies_to`` equals ticket type.
    2. Evaluate ``match`` conditions — unset/empty fields are wildcards.
    3. Among matches, pick highest specificity score (sum of dimension weights);
       ties break by lower ``priority_order``, then newer ``updated_at``.
    4. Attach that policy's response/resolution clocks only.
    Legacy policies without ``match`` behave as full wildcards (score 0).
    """
    tid = require_tenant_id(tenant_id)
    if ticket_type not in TICKET_TYPES:
        return []

    if ticket is None:
        try:
            ticket = ensure_ticket_exists(ticket_type, ticket_id, tenant_id=tid)
        except SlaError:
            ticket = {
                "priority": priority,
                "status": status,
            }

    context = build_ticket_context(ticket)
    if not context.get("priority"):
        context["priority"] = _norm(priority)

    policies = list(
        _policies().find(
            {"tenant_id": tid, "active": True, "applies_to": ticket_type}
        )
    )
    winner, score, matched = select_winning_policy(policies, context)
    if winner is None:
        return []

    # Skip if this policy already has open tracking for all its metrics.
    existing_metrics = {
        row["metric"]
        for row in _tracking().find(
            {
                "tenant_id": tid,
                "ticket_type": ticket_type,
                "ticket_id": ticket_id,
                "policy_id": winner["policy_id"],
                "status": {"$in": ["running", "paused"]},
            },
            {"metric": 1},
        )
    }
    filtered = dict(winner)
    filtered["targets"] = [
        t
        for t in (winner.get("targets") or [])
        if t.get("metric") not in existing_metrics
    ]
    if not filtered["targets"]:
        return []

    return _create_tracking_rows(
        tenant_id=tid,
        policy=filtered,
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        priority=priority,
        status=status,
        actor=actor,
        matched_fields=matched,
        match_score=score,
    )


def cancel_open_tracking(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    actor: dict[str, Any] | None = None,
    reason: str = "cancelled",
) -> int:
    tid = require_tenant_id(tenant_id)
    who = _actor_fields(actor)
    now = _now()
    result = _tracking().update_many(
        {
            "tenant_id": tid,
            "ticket_type": ticket_type,
            "ticket_id": ticket_id,
            "status": {"$in": ["running", "paused"]},
        },
        {
            "$set": {
                "status": "cancelled",
                "completed_at": now,
                "updated_at": now,
                "updated_by": who["username"],
                "cancel_reason": reason,
            }
        },
    )
    return int(result.modified_count)


def reattach_for_context_change(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    priority: str,
    status: str,
    actor: dict[str, Any] | None = None,
    reason: str = "context_change",
    ticket: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Cancel open clocks and attach the winning policy for the updated ticket."""
    cancel_open_tracking(
        tenant_id=tenant_id,
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        actor=actor,
        reason=reason,
    )
    return attach_matching_policies(
        tenant_id=tenant_id,
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        priority=priority,
        status=status,
        actor=actor,
        ticket=ticket,
    )


def reattach_for_priority_change(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    priority: str,
    status: str,
    actor: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Cancel open clocks and attach fresh tracking for the new priority."""
    return reattach_for_context_change(
        tenant_id=tenant_id,
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        priority=priority,
        status=status,
        actor=actor,
        reason="priority_change",
    )


def match_context_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """True when SLA-relevant ticket fields changed."""
    for field in _MATCH_CONTEXT_FIELDS:
        if _norm(before.get(field)) != _norm(after.get(field)):
            return True
    return False


def _pause_row(doc: dict[str, Any], *, actor: dict[str, Any] | None) -> dict[str, Any]:
    if doc.get("status") != "running":
        return doc
    who = _actor_fields(actor)
    now = _now()
    calendar = doc.get("calendar_snapshot") or {}
    elapsed = int(doc.get("elapsed_business_seconds") or 0)
    running_since = _ensure_aware(doc.get("running_since")) or _ensure_aware(
        doc.get("started_at")
    )
    if is_business_hours_calendar(calendar) and running_since is not None:
        elapsed += business_seconds_between(running_since, now, calendar)
    updated = _tracking().find_one_and_update(
        {
            "tenant_id": doc["tenant_id"],
            "tracking_id": doc["tracking_id"],
            "status": "running",
        },
        {
            "$set": {
                "status": "paused",
                "paused_at": now,
                "running_since": None,
                "elapsed_business_seconds": elapsed,
                "updated_at": now,
                "updated_by": who["username"],
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    return updated or doc


def _resume_row(doc: dict[str, Any], *, actor: dict[str, Any] | None) -> dict[str, Any]:
    if doc.get("status") != "paused":
        return doc
    who = _actor_fields(actor)
    now = _now()
    paused_at = _ensure_aware(doc.get("paused_at"))
    extra = 0
    if paused_at is not None:
        extra = max(0, int((now - paused_at).total_seconds()))
    paused_total = int(doc.get("paused_total_seconds") or 0) + extra
    calendar = doc.get("calendar_snapshot") or {}
    elapsed = int(doc.get("elapsed_business_seconds") or 0)
    due = _ensure_aware(doc.get("due_at")) or now
    target_minutes = int(doc.get("target_minutes") or 0)
    new_due = compute_due_after_resume(
        now=now,
        target_minutes=target_minutes,
        elapsed_business_seconds=elapsed,
        calendar=calendar,
        due_at=due,
        paused_wall_seconds=extra,
    )
    updated = _tracking().find_one_and_update(
        {
            "tenant_id": doc["tenant_id"],
            "tracking_id": doc["tracking_id"],
            "status": "paused",
        },
        {
            "$set": {
                "status": "running",
                "paused_at": None,
                "paused_total_seconds": paused_total,
                "elapsed_business_seconds": elapsed,
                "running_since": now,
                "due_at": new_due,
                "updated_at": now,
                "updated_by": who["username"],
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    return updated or doc


def _complete_metric(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    metric: str,
    actor: dict[str, Any] | None,
) -> None:
    who = _actor_fields(actor)
    now = _now()
    coll = _tracking()
    for doc in coll.find(
        {
            "tenant_id": tenant_id,
            "ticket_type": ticket_type,
            "ticket_id": ticket_id,
            "metric": metric,
            "status": {"$in": ["running", "paused"]},
        }
    ):
        due = _ensure_aware(doc.get("due_at"))
        # If currently paused, fold pause time into due before judging.
        if doc.get("status") == "paused":
            paused_at = _ensure_aware(doc.get("paused_at"))
            if paused_at and due:
                due = due + timedelta(seconds=max(0, int((now - paused_at).total_seconds())))
        met = due is None or now <= due
        coll.update_one(
            {"tenant_id": tenant_id, "tracking_id": doc["tracking_id"]},
            {
                "$set": {
                    "status": "met" if met else "breached",
                    "completed_at": now,
                    "breached_at": None if met else (due or now),
                    "paused_at": None,
                    "updated_at": now,
                    "updated_by": who["username"],
                }
            },
        )


def sync_on_status_change(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    from_status: str,
    to_status: str,
    priority: str,
    actor: dict[str, Any] | None = None,
    pause_on_statuses: list[str] | None = None,
) -> None:
    """Pause / resume / complete clocks when ticket status changes."""
    tid = require_tenant_id(tenant_id)
    # Refresh breaches first.
    now = _now()
    _tracking().update_many(
        {
            "tenant_id": tid,
            "ticket_type": ticket_type,
            "ticket_id": ticket_id,
            "status": "running",
            "due_at": {"$lt": now},
        },
        {"$set": {"status": "breached", "breached_at": now, "updated_at": now}},
    )

    # Derive pause set from attached policies if not provided.
    pause_set: set[str] = set(pause_on_statuses or [])
    if not pause_set:
        for policy in _policies().find(
            {"tenant_id": tid, "active": True, "applies_to": ticket_type}
        ):
            pause_set.update(policy.get("pause_on_statuses") or [])
        if not pause_set:
            pause_set.update(_DEFAULT_PAUSE.get(ticket_type, []))

    rows = list(
        _tracking().find(
            {
                "tenant_id": tid,
                "ticket_type": ticket_type,
                "ticket_id": ticket_id,
                "status": {"$in": ["running", "paused"]},
            }
        )
    )

    entering_pause = to_status in pause_set and from_status not in pause_set
    leaving_pause = from_status in pause_set and to_status not in pause_set

    if entering_pause:
        for row in rows:
            _pause_row(row, actor=actor)
    elif leaving_pause:
        for row in rows:
            _resume_row(row, actor=actor)

    # Response clock completes when leaving the initial status.
    initials = _INITIAL_BY_TYPE.get(ticket_type, frozenset())
    if from_status in initials and to_status not in initials:
        _complete_metric(
            tenant_id=tid,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            metric="response",
            actor=actor,
        )

    # Resolution clock completes on terminal statuses.
    terminals = _TERMINAL_BY_TYPE.get(ticket_type, frozenset())
    if to_status in terminals:
        _complete_metric(
            tenant_id=tid,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            metric="resolution",
            actor=actor,
        )
        # Cancel leftover response clocks if still open.
        cancel_open_tracking(
            tenant_id=tid,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            actor=actor,
            reason=f"ticket_{to_status}",
        )

    # Ensure policies are attached if somehow missing (e.g. policy created later).
    # Only on create path we auto-attach; here we keep best-effort soft attach when none exist.
    open_count = _tracking().count_documents(
        {
            "tenant_id": tid,
            "ticket_type": ticket_type,
            "ticket_id": ticket_id,
            "status": {"$in": ["running", "paused", "met", "breached"]},
        }
    )
    if open_count == 0 and to_status not in terminals:
        attach_matching_policies(
            tenant_id=tid,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            priority=priority,
            status=to_status,
            actor=actor,
        )


def notify_ticket_created(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    priority: str,
    status: str,
    actor: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Hook for ticket create — never raises to callers (best-effort)."""
    try:
        return attach_matching_policies(
            tenant_id=tenant_id,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            priority=priority,
            status=status,
            actor=actor,
        )
    except Exception:  # noqa: BLE001 — ticket create must not fail on SLA
        return []


def notify_priority_changed(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    priority: str,
    status: str,
    actor: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        return reattach_for_priority_change(
            tenant_id=tenant_id,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            priority=priority,
            status=status,
            actor=actor,
        )
    except Exception:  # noqa: BLE001
        return []


def notify_context_changed(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    priority: str,
    status: str,
    actor: dict[str, Any] | None = None,
    ticket: dict[str, Any] | None = None,
    reason: str = "context_change",
) -> list[dict[str, Any]]:
    try:
        return reattach_for_context_change(
            tenant_id=tenant_id,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            priority=priority,
            status=status,
            actor=actor,
            reason=reason,
            ticket=ticket,
        )
    except Exception:  # noqa: BLE001
        return []


def notify_status_changed(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    from_status: str,
    to_status: str,
    priority: str,
    actor: dict[str, Any] | None = None,
) -> None:
    try:
        sync_on_status_change(
            tenant_id=tenant_id,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            from_status=from_status,
            to_status=to_status,
            priority=priority,
            actor=actor,
        )
    except Exception:  # noqa: BLE001
        return
