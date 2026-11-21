"""ITSM AI assists — workflow / next-step suggestions (I6) + optional problem draft (I7).

Assist only. Never auto-advances workflows, transitions, or approvals.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ...services import ai_facade as ai_facade_service
from ...services.ai_providers import SOURCE_CLOUD, SOURCE_OLLAMA, SOURCE_RULE
from ...tenancy import require_tenant_id
from ..models.common import (
    CHANGE_TRANSITIONS,
    INCIDENT_TRANSITIONS,
    PROBLEM_TRANSITIONS,
)
from . import approvals as approvals_service
from . import changes as changes_service
from . import incidents as incidents_service
from . import problems as problems_service
from . import workflows as workflows_service
from .approvals import ApprovalError
from .changes import ChangeError
from .incidents import IncidentError
from .problems import ProblemError
from .workflows import WorkflowError

logger = logging.getLogger(__name__)

_TRANSITIONS = {
    "incident": INCIDENT_TRANSITIONS,
    "change": CHANGE_TRANSITIONS,
    "problem": PROBLEM_TRANSITIONS,
}


class ProcessAssistError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _load_ticket(
    ticket_type: str, ticket_id: str, *, tenant_id: str
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if ticket_type == "incident":
        doc = incidents_service.get_incident(ticket_id, tenant_id=tid)
        if doc is None:
            raise IncidentError(f"Incident '{ticket_id}' not found", status_code=404)
        return doc
    if ticket_type == "change":
        doc = changes_service.get_change(ticket_id, tenant_id=tid)
        if doc is None:
            raise ChangeError(f"Change '{ticket_id}' not found", status_code=404)
        return doc
    if ticket_type == "problem":
        doc = problems_service.get_problem(ticket_id, tenant_id=tid)
        if doc is None:
            raise ProblemError(f"Problem '{ticket_id}' not found", status_code=404)
        return doc
    raise ProcessAssistError(f"Invalid ticket_type '{ticket_type}'")


def _legal_next(ticket_type: str, status: str) -> list[str]:
    table = _TRANSITIONS.get(ticket_type) or {}
    return sorted(table.get(str(status or ""), frozenset()))


def _suggest_workflows(
    *, tenant_id: str, ticket_type: str, status: str
) -> list[dict[str, Any]]:
    try:
        listed = workflows_service.list_workflows(
            tenant_id=tenant_id,
            applies_to=ticket_type,
            active=True,
            page=1,
            page_size=25,
        )
        generic = workflows_service.list_workflows(
            tenant_id=tenant_id,
            applies_to="generic",
            active=True,
            page=1,
            page_size=10,
        )
    except WorkflowError as exc:
        logger.info("workflow list for next-steps skipped: %s", exc)
        return []
    rows = list(listed.get("items") or []) + list(generic.get("items") or [])
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for wf in rows:
        wid = str(wf.get("workflow_id") or "")
        if not wid or wid in seen:
            continue
        seen.add(wid)
        trigger = str(wf.get("trigger") or "")
        cfg = wf.get("trigger_config") or {}
        reason = f"active {trigger} workflow for {wf.get('applies_to')}"
        if trigger == "on_status":
            statuses = {
                str(s).lower() for s in (cfg.get("statuses") or []) if s is not None
            }
            if statuses and str(status).lower() not in statuses:
                continue
            reason = f"on_status match for '{status}'"
        elif trigger == "on_create" and status not in {"new", "draft"}:
            # Still listable as optional manual start, but note mismatch
            reason = "on_create workflow (ticket already past create) — manual start only"
        out.append(
            {
                "workflow_id": wid,
                "name": wf.get("name"),
                "trigger": trigger,
                "applies_to": wf.get("applies_to"),
                "match_reason": reason,
            }
        )
        if len(out) >= 8:
            break
    return out


def _open_approvals(
    *, tenant_id: str, ticket_type: str, ticket_id: str
) -> list[dict[str, Any]]:
    try:
        listed = approvals_service.list_approvals(
            tenant_id=tenant_id,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            status="pending",
            page=1,
            page_size=10,
        )
    except ApprovalError as exc:
        logger.info("approval list for next-steps skipped: %s", exc)
        return []
    items = []
    for row in listed.get("items") or []:
        items.append(
            {
                "approval_id": row.get("approval_id"),
                "title": row.get("title") or row.get("name"),
                "status": row.get("status"),
                "approver_group": row.get("approver_group"),
            }
        )
    return items


def _problem_draft(incident: dict[str, Any]) -> dict[str, Any] | None:
    """Optional I7 — draft only; never creates a problem."""
    status = str(incident.get("status") or "")
    if status not in {"resolved", "closed", "in_progress"}:
        return None
    title = str(incident.get("title") or "Recurring issue").strip()
    return {
        "title": f"Problem: {title}"[:500],
        "description": (
            f"Drafted from incident {incident.get('number_display') or incident.get('incident_id')}. "
            f"Category={incident.get('category') or 'unspecified'}. "
            f"Original description: {(incident.get('description') or '')[:1200]}"
        ),
        "known_error": False,
        "source_incident_id": incident.get("incident_id"),
        "note": "Assist draft only — human must create/link the problem.",
    }


def build_next_steps_fallback(
    ticket: dict[str, Any],
    *,
    ticket_type: str,
    tenant_id: str,
    reason: str,
) -> dict[str, Any]:
    status = str(ticket.get("status") or "")
    legal = _legal_next(ticket_type, status)
    workflows = _suggest_workflows(
        tenant_id=tenant_id, ticket_type=ticket_type, status=status
    )
    ticket_id_field = {
        "incident": "incident_id",
        "change": "change_id",
        "problem": "problem_id",
    }[ticket_type]
    ticket_id = str(ticket.get(ticket_id_field) or "")
    approvals = _open_approvals(
        tenant_id=tenant_id, ticket_type=ticket_type, ticket_id=ticket_id
    )
    actions: list[str] = []
    if approvals:
        actions.append("Review pending approval(s) — decide approve/reject as a human.")
    if workflows:
        actions.append(
            f"Consider starting workflow '{workflows[0].get('name')}' "
            f"({workflows[0].get('workflow_id')}) — manual start only."
        )
    if legal:
        actions.append(
            "Legal next statuses (human transition required): " + ", ".join(legal)
        )
    else:
        actions.append("No further legal status transitions from current state.")
    actions.append("AI will not advance workflows, approvals, or ticket status.")

    problem_draft = None
    if ticket_type == "incident":
        problem_draft = _problem_draft(ticket)

    summary = (
        f"Next-step assist for {ticket_type}/{ticket.get('number_display') or ticket_id}: "
        f"status={status}; {len(legal)} legal transition(s); "
        f"{len(workflows)} workflow suggestion(s); {len(approvals)} pending approval(s)."
    )
    return {
        "source": SOURCE_RULE,
        "fallback_reason": reason,
        "model": None,
        "ticket_type": ticket_type,
        "ticket_id": ticket_id,
        "current_status": status,
        "legal_next_statuses": legal,
        "suggested_workflows": workflows,
        "pending_approvals": approvals,
        "suggested_actions": actions,
        "problem_draft": problem_draft,
        "summary": summary,
        "safety": {
            "assist_only": True,
            "no_auto_transition": True,
            "no_auto_advance": True,
            "no_auto_approve": True,
            "human_must_confirm": True,
        },
    }


def _normalize_next_steps(
    raw: dict[str, Any],
    *,
    fallback: dict[str, Any],
    source: str,
    model: str | None,
) -> dict[str, Any]:
    legal = set(fallback.get("legal_next_statuses") or [])
    next_raw = raw.get("legal_next_statuses") or fallback.get("legal_next_statuses") or []
    if isinstance(next_raw, str):
        next_raw = [next_raw]
    next_statuses = [str(s) for s in next_raw if str(s) in legal] or sorted(legal)

    allowed_wf = {
        str(w.get("workflow_id")): w for w in (fallback.get("suggested_workflows") or [])
    }
    wfs: list[dict[str, Any]] = []
    for item in raw.get("suggested_workflows") or []:
        if not isinstance(item, dict):
            continue
        base = allowed_wf.get(str(item.get("workflow_id") or ""))
        if not base:
            continue
        row = dict(base)
        if item.get("match_reason"):
            row["match_reason"] = str(item["match_reason"])[:240]
        wfs.append(row)
    if not wfs:
        wfs = list(fallback.get("suggested_workflows") or [])

    actions = raw.get("suggested_actions") or fallback.get("suggested_actions") or []
    if isinstance(actions, str):
        actions = [actions]
    return {
        "source": source,
        "model": model,
        "ticket_type": fallback.get("ticket_type"),
        "ticket_id": fallback.get("ticket_id"),
        "current_status": fallback.get("current_status"),
        "legal_next_statuses": next_statuses,
        "suggested_workflows": wfs,
        "pending_approvals": fallback.get("pending_approvals") or [],
        "suggested_actions": [str(a).strip() for a in actions if str(a).strip()][:10],
        "problem_draft": fallback.get("problem_draft"),
        "summary": str(raw.get("summary") or fallback.get("summary") or "").strip()
        or fallback.get("summary"),
        "safety": fallback.get("safety"),
    }


def _validate_next_steps(raw: dict[str, Any]) -> None:
    if "summary" not in raw and "legal_next_statuses" not in raw:
        raise ValueError("next-steps JSON missing summary/legal_next_statuses")


def suggest_next_steps(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    force_fallback: bool = False,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    ticket_type = str(ticket_type or "").strip().lower()
    ticket_id = str(ticket_id or "").strip()
    if ticket_type not in _TRANSITIONS:
        raise ProcessAssistError(f"Invalid ticket_type '{ticket_type}'")
    ticket = _load_ticket(ticket_type, ticket_id, tenant_id=tid)

    def _fallback(reason: str) -> dict[str, Any]:
        return build_next_steps_fallback(
            ticket, ticket_type=ticket_type, tenant_id=tid, reason=reason
        )

    base = _fallback("rule_based_fallback")
    prompt = {
        "ticket": {
            "ticket_type": ticket_type,
            "ticket_id": ticket_id,
            "title": ticket.get("title"),
            "status": ticket.get("status"),
            "priority": ticket.get("priority"),
        },
        "legal_next_statuses": base.get("legal_next_statuses"),
        "suggested_workflows": base.get("suggested_workflows"),
        "pending_approvals": base.get("pending_approvals"),
        "instruction": (
            "Enrich summary and suggested_actions only. "
            "Do not invent workflow_ids or statuses outside legal_next_statuses. "
            "Never auto-transition or approve."
        ),
    }
    system = (
        "You are an ITSM next-step assistant for SVRMON24. "
        "Respond with a single JSON object only. "
        "Never auto-advance workflows, approvals, or transitions. "
        "Required keys: summary, legal_next_statuses (subset of provided), "
        "suggested_workflows (subset by workflow_id), suggested_actions (array)."
    )
    result = ai_facade_service.safe_run_structured_task(
        task_key="itsm.next_steps",
        tenant_id=tid,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Draft next-step assist as JSON:\n"
                + json.dumps(prompt, default=str),
            },
        ],
        fallback_builder=lambda reason: base
        if reason == "rule_based_fallback"
        else _fallback(reason),
        validate_fn=_validate_next_steps,
        force_fallback=force_fallback,
        record_usage=True,
    )
    if result.source in {SOURCE_OLLAMA, SOURCE_CLOUD}:
        return _normalize_next_steps(
            result.payload if isinstance(result.payload, dict) else {},
            fallback=base,
            source=result.source,
            model=result.model,
        )
    payload = result.payload
    if isinstance(payload, dict) and (
        payload.get("summary") is not None or payload.get("legal_next_statuses") is not None
    ):
        if payload.get("safety"):
            return payload
        return _normalize_next_steps(
            payload, fallback=base, source=SOURCE_RULE, model=None
        )
    return _fallback(result.fallback_reason or "rule_based_fallback")
