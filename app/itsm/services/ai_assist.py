"""ITSM AI assists — incident triage (I1) and summarization (I2).

Assist / suggestion only. Apply via IncidentUpdate / transition APIs.
AI errors never fail ticket mutations (facade safe path + callers treat as side-call).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ...services import ai_facade as ai_facade_service
from ...services.ai_providers import SOURCE_CLOUD, SOURCE_OLLAMA, SOURCE_RULE
from ...tenancy import require_tenant_id
from ..models.common import INCIDENT_PRIORITIES, INCIDENT_TRANSITIONS
from . import activities as activities_service
from . import incidents as incidents_service
from .incidents import IncidentError

logger = logging.getLogger(__name__)

_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("network", ("network", "dns", "vpn", "firewall", "latency", "packet", "wifi")),
    ("database", ("database", "db", "sql", "oracle", "postgres", "mysql", "mongo")),
    ("application", ("application", "app", "http", "api", "portal", "ui", "500")),
    ("access", ("access", "login", "auth", "permission", "sso", "password", "locked")),
    ("infrastructure", ("server", "cpu", "memory", "disk", "host", "vm", "storage")),
    ("email", ("email", "smtp", "mailbox", "outlook")),
]


def _blob(*parts: Any) -> str:
    return " ".join(str(p).strip().lower() for p in parts if p is not None and str(p).strip())


def _priority_from_text(text: str, *, ci_criticality: str | None) -> str:
    crit = (ci_criticality or "").strip().lower()
    if any(k in text for k in ("outage", "down", "sev1", "severity", "production down")):
        return "p1"
    if crit in {"critical", "mission_critical", "tier1"}:
        return "p1"
    if any(k in text for k in ("degraded", "slow", "sev2", "major", "partial outage")):
        return "p2"
    if crit in {"high"}:
        return "p2"
    if any(k in text for k in ("minor", "sev4", "cosmetic", "question", "how to")):
        return "p4"
    return "p3"


def _category_from_text(text: str) -> tuple[str | None, str | None]:
    for category, keys in _CATEGORY_KEYWORDS:
        if any(k in text for k in keys):
            return category, None
    return None, None


def _group_from_category(category: str | None) -> str | None:
    if not category:
        return None
    return f"{category}-support"


def build_triage_fallback(incident: dict[str, Any], *, reason: str) -> dict[str, Any]:
    text = _blob(
        incident.get("title"),
        incident.get("description"),
        incident.get("urgency"),
        incident.get("impact"),
        incident.get("category"),
        incident.get("ci_criticality"),
    )
    priority = _priority_from_text(text, ci_criticality=incident.get("ci_criticality"))
    category, subcategory = _category_from_text(text)
    if incident.get("category"):
        category = str(incident["category"])
    group = incident.get("assignment_group") or _group_from_category(category)
    summary = (
        f"Rule triage for {incident.get('number') or incident.get('incident_id')}: "
        f"priority={priority}, category={category or 'unspecified'}. "
        f"Based on keywords + CI criticality only."
    )
    return {
        "source": SOURCE_RULE,
        "fallback_reason": reason,
        "model": None,
        "suggested_priority": priority,
        "suggested_category": category,
        "suggested_subcategory": subcategory,
        "suggested_assignment_group": group,
        "triage_summary": summary,
        "confidence": "low",
        "safety": {
            "assist_only": True,
            "auto_apply": False,
            "human_must_confirm": True,
            "no_auto_transition": True,
        },
        "apply_fields": {
            k: v
            for k, v in {
                "priority": priority,
                "category": category,
                "subcategory": subcategory,
                "assignment_group": group,
            }.items()
            if v is not None
        },
    }


def _normalize_triage(
    raw: dict[str, Any],
    *,
    source: str,
    model: str | None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    priority = str(raw.get("suggested_priority") or raw.get("priority") or "p3").lower()
    if priority not in INCIDENT_PRIORITIES:
        priority = "p3"
    category = raw.get("suggested_category") or raw.get("category")
    if category is not None:
        category = str(category).strip()[:128] or None
    subcategory = raw.get("suggested_subcategory") or raw.get("subcategory")
    if subcategory is not None:
        subcategory = str(subcategory).strip()[:128] or None
    group = raw.get("suggested_assignment_group") or raw.get("assignment_group")
    if group is not None:
        group = str(group).strip()[:128] or None
    confidence = str(raw.get("confidence") or "low").lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"
    out: dict[str, Any] = {
        "source": source,
        "model": model,
        "suggested_priority": priority,
        "suggested_category": category,
        "suggested_subcategory": subcategory,
        "suggested_assignment_group": group,
        "triage_summary": str(raw.get("triage_summary") or "").strip()
        or "Triage suggestion produced.",
        "confidence": confidence,
        "safety": {
            "assist_only": True,
            "auto_apply": False,
            "human_must_confirm": True,
            "no_auto_transition": True,
        },
        "apply_fields": {
            k: v
            for k, v in {
                "priority": priority,
                "category": category,
                "subcategory": subcategory,
                "assignment_group": group,
            }.items()
            if v is not None
        },
    }
    if fallback_reason:
        out["fallback_reason"] = fallback_reason
    return out


def _validate_triage(raw: dict[str, Any]) -> None:
    if "suggested_priority" not in raw and "priority" not in raw:
        raise ValueError("triage JSON missing suggested_priority")


def suggest_incident_triage(
    incident_id: str,
    *,
    tenant_id: str,
    force_fallback: bool = False,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    incident = incidents_service.get_incident(incident_id, tenant_id=tid)
    if incident is None:
        raise IncidentError(f"Incident '{incident_id}' not found", status_code=404)

    def _fallback(reason: str) -> dict[str, Any]:
        return build_triage_fallback(incident, reason=reason)

    prompt = {
        "incident": {
            "incident_id": incident.get("incident_id"),
            "number": incident.get("number"),
            "title": incident.get("title"),
            "description": (incident.get("description") or "")[:4000],
            "status": incident.get("status"),
            "priority": incident.get("priority"),
            "urgency": incident.get("urgency"),
            "impact": incident.get("impact"),
            "category": incident.get("category"),
            "subcategory": incident.get("subcategory"),
            "assignment_group": incident.get("assignment_group"),
            "ci_criticality": incident.get("ci_criticality"),
            "ci_links": incident.get("ci_links") or [],
        },
        "allowed_priorities": list(INCIDENT_PRIORITIES),
    }
    system = (
        "You are an ITSM incident triage assistant for SVRMON24. "
        "Respond with a single JSON object only. "
        "Suggest priority from p1|p2|p3|p4, category/subcategory, assignment_group, "
        "and a short triage_summary. Assist only — never transition or close the ticket. "
        "Required keys: suggested_priority, suggested_category, suggested_subcategory, "
        "suggested_assignment_group, triage_summary, confidence (low|medium|high)."
    )
    result = ai_facade_service.safe_run_structured_task(
        task_key="itsm.incident_triage",
        tenant_id=tid,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Triage this incident as JSON:\n"
                + json.dumps(prompt, default=str),
            },
        ],
        fallback_builder=_fallback,
        validate_fn=_validate_triage,
        force_fallback=force_fallback,
        record_usage=True,
    )
    if result.source in {SOURCE_OLLAMA, SOURCE_CLOUD}:
        return _normalize_triage(
            result.payload, source=result.source, model=result.model
        )
    payload = result.payload
    if isinstance(payload, dict) and payload.get("suggested_priority"):
        return payload
    return _fallback(result.fallback_reason or "rule_based_fallback")


def build_summary_fallback(
    incident: dict[str, Any],
    activities: list[dict[str, Any]],
    *,
    reason: str,
) -> dict[str, Any]:
    lines: list[str] = [
        f"Status={incident.get('status')} priority={incident.get('priority')} "
        f"updated={incident.get('updated_at')}."
    ]
    for act in activities[:8]:
        lines.append(
            f"- {act.get('activity_type')}: "
            f"{str(act.get('body') or act.get('comment') or act.get('message') or '')[:240]}"
        )
    open_q = []
    if not incident.get("assignment_group"):
        open_q.append("Assignment group still blank?")
    if incident.get("status") in {"new", "in_progress"} and not incident.get(
        "resolution_notes"
    ):
        open_q.append("Resolution notes not yet drafted.")
    status = str(incident.get("status") or "")
    next_statuses = sorted(INCIDENT_TRANSITIONS.get(status, frozenset()))
    resolution_draft = None
    if status in {"in_progress", "on_hold", "resolved"}:
        resolution_draft = (
            f"Resolved based on investigation of '{incident.get('title')}'. "
            "Confirm with requester before close. (rule draft — human must apply)"
        )
    return {
        "source": SOURCE_RULE,
        "fallback_reason": reason,
        "model": None,
        "timeline_summary": " ".join(lines[:12]),
        "open_questions": open_q,
        "suggested_next_statuses": next_statuses,
        "resolution_notes_draft": resolution_draft,
        "safety": {
            "assist_only": True,
            "auto_apply": False,
            "no_auto_transition": True,
            "human_must_confirm": True,
        },
    }


def _normalize_summary(
    raw: dict[str, Any],
    *,
    incident: dict[str, Any],
    source: str,
    model: str | None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    status = str(incident.get("status") or "")
    legal = INCIDENT_TRANSITIONS.get(status, frozenset())
    next_raw = raw.get("suggested_next_statuses") or []
    if isinstance(next_raw, str):
        next_raw = [next_raw]
    next_statuses = [
        str(s)
        for s in next_raw
        if str(s) in legal
    ] or sorted(legal)
    questions = raw.get("open_questions") or []
    if isinstance(questions, str):
        questions = [questions]
    out: dict[str, Any] = {
        "source": source,
        "model": model,
        "timeline_summary": str(raw.get("timeline_summary") or "").strip()
        or "No summary produced.",
        "open_questions": [str(q).strip() for q in questions if str(q).strip()][:8],
        "suggested_next_statuses": next_statuses,
        "resolution_notes_draft": (
            str(raw.get("resolution_notes_draft")).strip()
            if raw.get("resolution_notes_draft")
            else None
        ),
        "safety": {
            "assist_only": True,
            "auto_apply": False,
            "no_auto_transition": True,
            "human_must_confirm": True,
        },
    }
    if fallback_reason:
        out["fallback_reason"] = fallback_reason
    return out


def _validate_summary(raw: dict[str, Any]) -> None:
    if "timeline_summary" not in raw:
        raise ValueError("summary JSON missing timeline_summary")


def summarize_incident(
    incident_id: str,
    *,
    tenant_id: str,
    force_fallback: bool = False,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    incident = incidents_service.get_incident(incident_id, tenant_id=tid)
    if incident is None:
        raise IncidentError(f"Incident '{incident_id}' not found", status_code=404)

    acts = activities_service.list_activities(
        tenant_id=tid,
        ticket_type="incident",
        ticket_id=incident_id,
        page=1,
        page_size=15,
    )
    activity_items = list(acts.get("items") or [])

    def _fallback(reason: str) -> dict[str, Any]:
        return build_summary_fallback(incident, activity_items, reason=reason)

    prompt = {
        "incident": {
            "incident_id": incident.get("incident_id"),
            "title": incident.get("title"),
            "description": (incident.get("description") or "")[:3000],
            "status": incident.get("status"),
            "priority": incident.get("priority"),
            "resolution_notes": incident.get("resolution_notes"),
        },
        "activities": [
            {
                "activity_type": a.get("activity_type"),
                "body": str(
                    a.get("body") or a.get("comment") or a.get("message") or ""
                )[:500],
                "created_at": a.get("created_at"),
            }
            for a in activity_items[:12]
        ],
        "legal_next_statuses": sorted(
            INCIDENT_TRANSITIONS.get(str(incident.get("status") or ""), frozenset())
        ),
    }
    system = (
        "You are an ITSM incident summarization assistant for SVRMON24. "
        "Respond with a single JSON object only. "
        "Summarize the timeline and list open questions. "
        "You may draft resolution_notes_draft for the human to apply — never transition. "
        "suggested_next_statuses must be a subset of legal_next_statuses. "
        "Required keys: timeline_summary, open_questions (array), "
        "suggested_next_statuses (array), resolution_notes_draft (string|null)."
    )
    result = ai_facade_service.safe_run_structured_task(
        task_key="itsm.incident_summary",
        tenant_id=tid,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Summarize this incident as JSON:\n"
                + json.dumps(prompt, default=str),
            },
        ],
        fallback_builder=_fallback,
        validate_fn=_validate_summary,
        force_fallback=force_fallback,
        record_usage=True,
    )
    if result.source in {SOURCE_OLLAMA, SOURCE_CLOUD}:
        return _normalize_summary(
            result.payload,
            incident=incident,
            source=result.source,
            model=result.model,
        )
    payload = result.payload
    if isinstance(payload, dict) and payload.get("timeline_summary"):
        return payload
    return _fallback(result.fallback_reason or "rule_based_fallback")
