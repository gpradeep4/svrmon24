"""ITSM AI assists — change risk text (I4) + SLA at-risk (I5).

Assist only. Never auto-approves CAB / never mutates SLA clocks or statuses.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ...cmdb.services import dependencies as dependencies_service
from ...services import ai_facade as ai_facade_service
from ...services.ai_providers import SOURCE_CLOUD, SOURCE_OLLAMA, SOURCE_RULE
from ...tenancy import require_tenant_id
from . import changes as changes_service
from . import sla as sla_service
from .changes import ChangeError
from .sla import SlaError

logger = logging.getLogger(__name__)

IMPACT_DISCLAIMER = (
    "Potential impact from CMDB relationships is not a current outage. "
    "Approvals and transitions remain human-gated."
)

_AT_RISK_FRACTION = 0.20  # <20% of target window remaining


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(dt: Any) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _risk_band(app_n: int, node_n: int, change_type: str | None, risk_hint: str | None) -> str:
    ct = (change_type or "").strip().lower()
    rh = (risk_hint or "").strip().lower()
    score = app_n * 2 + max(0, node_n - 1)
    if ct == "emergency" or rh in {"high", "critical"}:
        score += 4
    elif ct == "normal" or rh == "medium":
        score += 1
    elif ct == "standard" or rh == "low":
        score -= 1
    if score >= 6:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def _empty_impact() -> dict[str, Any]:
    return {
        "selected": {},
        "counts": {"nodes": 0, "potentially_affected_applications": 0},
        "potentially_affected_applications": [],
        "nodes": [],
    }


def _merge_impacts(impacts: list[dict[str, Any]]) -> dict[str, Any]:
    if not impacts:
        return _empty_impact()
    apps: dict[str, dict[str, Any]] = {}
    node_ids: set[str] = set()
    reported_nodes = 0
    for impact in impacts:
        try:
            reported_nodes = max(
                reported_nodes, int((impact.get("counts") or {}).get("nodes") or 0)
            )
        except (TypeError, ValueError):
            pass
        downstream = impact.get("downstream") or {}
        for node in list(downstream.get("nodes") or []) + list(impact.get("nodes") or []):
            if not isinstance(node, dict):
                continue
            cid = str(node.get("component_id") or "")
            if cid:
                node_ids.add(cid)
        for app in impact.get("potentially_affected_applications") or []:
            if not isinstance(app, dict):
                continue
            comp = app.get("component") if isinstance(app.get("component"), dict) else None
            if comp is not None:
                cid = str(comp.get("component_id") or "")
                name = comp.get("name")
            else:
                cid = str(app.get("component_id") or "")
                name = app.get("name")
            if not cid:
                continue
            apps[cid] = {
                "component_id": cid,
                "name": name,
                "depth": app.get("depth"),
                "direct_or_indirect": app.get("direct_or_indirect"),
            }
            node_ids.add(cid)
        selected = impact.get("selected") or {}
        sid = str(selected.get("component_id") or "")
        if sid:
            node_ids.add(sid)
    node_n = max(len(node_ids), reported_nodes)
    return {
        "selected": (impacts[0].get("selected") or {}) if impacts else {},
        "counts": {
            "nodes": node_n,
            "potentially_affected_applications": len(apps),
        },
        "potentially_affected_applications": list(apps.values()),
        "nodes": [{"component_id": x} for x in sorted(node_ids)],
        "merged_from": len(impacts),
    }


def _collect_change_impact(change: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
    cis = []
    for link in change.get("ci_links") or []:
        if isinstance(link, dict) and link.get("component_id"):
            cis.append(str(link["component_id"]))
    impacts: list[dict[str, Any]] = []
    for cid in cis[:5]:
        try:
            impacts.append(
                dependencies_service.analyze_impact(
                    cid, tenant_id=tenant_id, depth=8
                )
            )
        except Exception as exc:  # pragma: no cover — graph failures → empty
            logger.info("change risk impact failed for %s: %s", cid, exc)
    return _merge_impacts(impacts)


def build_change_risk_fallback(
    change: dict[str, Any],
    impact: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    apps = impact.get("potentially_affected_applications") or []
    counts = impact.get("counts") or {}
    app_n = int(counts.get("potentially_affected_applications") or len(apps))
    node_n = int(counts.get("nodes") or 0)
    band = _risk_band(
        app_n,
        node_n,
        change.get("change_type"),
        change.get("risk"),
    )
    checklist = [
        "Confirm maintenance window with owners of potentially affected apps.",
        "Verify backout/rollback plan before change start.",
        "Re-check CMDB CI links if topology looks incomplete.",
        "CAB/approvals remain human — AI does not approve.",
        IMPACT_DISCLAIMER,
    ]
    if change.get("backout_plan"):
        checklist.insert(0, "Review recorded backout plan on the change ticket.")
    if change.get("cab_required"):
        checklist.insert(0, "CAB required flag is set — route for human approval.")
    chg_label = change.get("number_display") or change.get("change_id")
    narrative = (
        f"Change-risk assist for {chg_label}: risk band {band} from "
        f"change_type={change.get('change_type') or 'unspecified'}, "
        f"risk hint={change.get('risk') or 'unspecified'}, "
        f"{app_n} potentially affected application(s), {node_n} graph node(s). "
        "Derived from change fields + CMDB impact counts only."
    )
    cited = sorted(
        {
            str(a.get("component_id"))
            for a in apps
            if a.get("component_id")
        }
        | {
            str(n.get("component_id"))
            for n in (impact.get("nodes") or [])
            if isinstance(n, dict) and n.get("component_id")
        }
    )
    return {
        "source": SOURCE_RULE,
        "fallback_reason": reason,
        "model": None,
        "change_id": change.get("change_id"),
        "risk_band": band,
        "narrative": narrative,
        "checklist": checklist,
        "affected_applications": apps[:20],
        "cited_component_ids": cited,
        "disclaimer": IMPACT_DISCLAIMER,
        "safety": {
            "assist_only": True,
            "no_auto_cab": True,
            "no_auto_approve": True,
            "no_auto_transition": True,
            "potential_impact_not_outage": True,
            "human_must_confirm": True,
        },
    }


def _normalize_change_risk(
    raw: dict[str, Any],
    *,
    fallback: dict[str, Any],
    source: str,
    model: str | None,
) -> dict[str, Any]:
    band = str(raw.get("risk_band") or fallback.get("risk_band") or "low").lower()
    if band not in {"low", "medium", "high"}:
        band = str(fallback.get("risk_band") or "low")
    allowed = set(fallback.get("cited_component_ids") or [])
    cited_raw = raw.get("cited_component_ids") or fallback.get("cited_component_ids") or []
    if isinstance(cited_raw, str):
        cited_raw = [cited_raw]
    cited = [str(c) for c in cited_raw if str(c) in allowed] or list(allowed)
    checklist = raw.get("checklist") or fallback.get("checklist") or []
    if isinstance(checklist, str):
        checklist = [checklist]
    return {
        "source": source,
        "model": model,
        "change_id": fallback.get("change_id"),
        "risk_band": band,
        "narrative": str(raw.get("narrative") or fallback.get("narrative") or "").strip()
        or fallback.get("narrative"),
        "checklist": [str(c).strip() for c in checklist if str(c).strip()][:12],
        "affected_applications": fallback.get("affected_applications") or [],
        "cited_component_ids": cited,
        "disclaimer": IMPACT_DISCLAIMER,
        "safety": fallback.get("safety"),
    }


def _validate_change_risk(raw: dict[str, Any]) -> None:
    if "risk_band" not in raw and "narrative" not in raw:
        raise ValueError("change risk JSON missing risk_band/narrative")


def suggest_change_risk(
    change_id: str,
    *,
    tenant_id: str,
    force_fallback: bool = False,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    change = changes_service.get_change(change_id, tenant_id=tid)
    if change is None:
        raise ChangeError(f"Change '{change_id}' not found", status_code=404)

    impact = _collect_change_impact(change, tenant_id=tid)

    def _fallback(reason: str) -> dict[str, Any]:
        return build_change_risk_fallback(change, impact, reason=reason)

    base = _fallback("rule_based_fallback")
    prompt = {
        "change": {
            "change_id": change.get("change_id"),
            "title": change.get("title"),
            "change_type": change.get("change_type"),
            "risk": change.get("risk"),
            "cab_required": change.get("cab_required"),
            "status": change.get("status"),
            "backout_plan": (change.get("backout_plan") or "")[:800],
        },
        "impact_counts": impact.get("counts"),
        "affected_applications": base.get("affected_applications"),
        "cited_component_ids": base.get("cited_component_ids"),
        "allowed_bands": ["low", "medium", "high"],
    }
    system = (
        "You are an ITSM change-risk assistant for SVRMON24. "
        "Respond with a single JSON object only. "
        "Cite only provided component ids. Never approve or transition. "
        "Required keys: risk_band (low|medium|high), narrative, checklist (array), "
        "cited_component_ids (subset of provided ids)."
    )
    result = ai_facade_service.safe_run_structured_task(
        task_key="itsm.change_risk",
        tenant_id=tid,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Draft change risk assist as JSON:\n"
                + json.dumps(prompt, default=str),
            },
        ],
        fallback_builder=lambda reason: base
        if reason == "rule_based_fallback"
        else _fallback(reason),
        validate_fn=_validate_change_risk,
        force_fallback=force_fallback,
        record_usage=True,
    )
    if result.source in {SOURCE_OLLAMA, SOURCE_CLOUD}:
        return _normalize_change_risk(
            result.payload if isinstance(result.payload, dict) else {},
            fallback=base,
            source=result.source,
            model=result.model,
        )
    payload = result.payload
    if isinstance(payload, dict) and payload.get("risk_band"):
        return payload
    return _fallback(result.fallback_reason or "rule_based_fallback")


def _evaluate_tracking(doc: dict[str, Any]) -> dict[str, Any]:
    status = str(doc.get("status") or "")
    started = _ensure_aware(doc.get("started_at"))
    due = _ensure_aware(doc.get("due_at"))
    now = _now()
    target_minutes = int(doc.get("target_minutes") or 0)
    remaining_minutes: float | None = None
    fraction_remaining: float | None = None
    at_risk = False
    reason = "ok"

    if status == "breached":
        at_risk = True
        reason = "already_breached"
        remaining_minutes = 0.0
        fraction_remaining = 0.0
    elif status == "paused":
        reason = "paused"
        if due and now:
            remaining_minutes = max(0.0, (due - now).total_seconds() / 60.0)
    elif status in {"met", "cancelled"}:
        reason = f"terminal_{status}"
    elif status == "running" and due is not None:
        remaining_minutes = (due - now).total_seconds() / 60.0
        if remaining_minutes <= 0:
            at_risk = True
            reason = "past_due"
            remaining_minutes = 0.0
            fraction_remaining = 0.0
        else:
            total_seconds = None
            if started is not None:
                total_seconds = (due - started).total_seconds()
            elif target_minutes > 0:
                total_seconds = target_minutes * 60.0
            if total_seconds and total_seconds > 0:
                fraction_remaining = remaining_minutes * 60.0 / total_seconds
                if fraction_remaining < _AT_RISK_FRACTION:
                    at_risk = True
                    reason = "under_20pct_remaining"
            elif target_minutes > 0 and remaining_minutes < target_minutes * _AT_RISK_FRACTION:
                at_risk = True
                reason = "under_20pct_remaining"
                fraction_remaining = remaining_minutes / float(target_minutes)

    actions: list[str] = []
    if at_risk and status == "breached":
        actions = [
            "Acknowledge breach with requester/stakeholders.",
            "Update ticket with delay reason; consider priority/escalation.",
            "Do not expect AI to reset SLA clocks — clocks stay as recorded.",
        ]
    elif at_risk:
        actions = [
            "Prioritize work on this ticket before the SLA due time.",
            "Add a progress comment or escalate to the assignment group.",
            "If waiting on customer, transition to an SLA pause status if policy allows.",
            "AI will not mutate SLA tracking — human actions only.",
        ]
    elif status == "paused":
        actions = [
            "Resume when blocker clears; confirm pause status is still valid.",
        ]
    else:
        actions = [
            "Continue normal handling; re-check assist closer to due_at.",
        ]

    narrative = (
        f"SLA {doc.get('metric')} on {doc.get('ticket_type')}/{doc.get('ticket_id')}: "
        f"status={status}, at_risk={at_risk} ({reason}). "
        f"Remaining≈{remaining_minutes:.1f}m"
        if remaining_minutes is not None
        else f"SLA {doc.get('metric')}: status={status}, at_risk={at_risk} ({reason})."
    )
    if fraction_remaining is not None:
        narrative += f", fraction_remaining≈{fraction_remaining:.2f}."

    return {
        "tracking_id": doc.get("tracking_id"),
        "metric": doc.get("metric"),
        "status": status,
        "priority_at_start": doc.get("priority_at_start"),
        "target_minutes": target_minutes,
        "due_at": doc.get("due_at"),
        "started_at": doc.get("started_at"),
        "remaining_minutes": remaining_minutes,
        "fraction_remaining": fraction_remaining,
        "at_risk": at_risk,
        "reason": reason,
        "narrative": narrative,
        "suggested_actions": actions,
    }


def build_sla_at_risk_fallback(
    evaluations: list[dict[str, Any]],
    *,
    ticket_type: str,
    ticket_id: str,
    reason: str,
) -> dict[str, Any]:
    any_risk = any(e.get("at_risk") for e in evaluations)
    summary = (
        f"SLA at-risk assist for {ticket_type}/{ticket_id}: "
        f"{'AT RISK' if any_risk else 'within target window'} "
        f"across {len(evaluations)} tracking row(s). Deterministic clocks only."
    )
    return {
        "source": SOURCE_RULE,
        "fallback_reason": reason,
        "model": None,
        "ticket_type": ticket_type,
        "ticket_id": ticket_id,
        "at_risk": any_risk,
        "summary": summary,
        "items": evaluations,
        "safety": {
            "assist_only": True,
            "no_clock_mutation": True,
            "no_status_mutation": True,
            "human_must_confirm": True,
        },
    }


def _normalize_sla(
    raw: dict[str, Any],
    *,
    fallback: dict[str, Any],
    source: str,
    model: str | None,
) -> dict[str, Any]:
    # Preserve deterministic at_risk flags; LLM may only enrich narrative/actions.
    items = list(fallback.get("items") or [])
    by_id = {str(i.get("tracking_id")): i for i in items}
    for raw_item in raw.get("items") or []:
        if not isinstance(raw_item, dict):
            continue
        tid = str(raw_item.get("tracking_id") or "")
        base = by_id.get(tid)
        if not base:
            continue
        if raw_item.get("narrative"):
            base["narrative"] = str(raw_item["narrative"])[:600]
        acts = raw_item.get("suggested_actions")
        if isinstance(acts, list) and acts:
            base["suggested_actions"] = [str(a)[:200] for a in acts[:6]]
    summary = str(raw.get("summary") or fallback.get("summary") or "").strip()
    return {
        "source": source,
        "model": model,
        "ticket_type": fallback.get("ticket_type"),
        "ticket_id": fallback.get("ticket_id"),
        "at_risk": bool(fallback.get("at_risk")),
        "summary": summary or fallback.get("summary"),
        "items": items,
        "safety": fallback.get("safety"),
    }


def _validate_sla(raw: dict[str, Any]) -> None:
    if "summary" not in raw and "items" not in raw:
        raise ValueError("sla assist JSON missing summary/items")


def suggest_sla_at_risk(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    force_fallback: bool = False,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    ticket_type = str(ticket_type or "").strip().lower()
    ticket_id = str(ticket_id or "").strip()
    if ticket_type not in {"incident", "change", "problem"}:
        raise SlaError(f"Invalid ticket_type '{ticket_type}'")
    if not ticket_id:
        raise SlaError("ticket_id required")

    listed = sla_service.list_tracking(
        tenant_id=tid,
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        page=1,
        page_size=50,
    )
    rows = list(listed.get("items") or [])
    evaluations = [_evaluate_tracking(row) for row in rows]

    def _fallback(reason: str) -> dict[str, Any]:
        return build_sla_at_risk_fallback(
            evaluations,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            reason=reason,
        )

    base = _fallback("rule_based_fallback")
    prompt = {
        "ticket_type": ticket_type,
        "ticket_id": ticket_id,
        "items": evaluations,
        "instruction": (
            "Enrich narratives and suggested_actions only. "
            "Do not change at_risk flags or invent tracking_ids. "
            "Never mutate SLA clocks."
        ),
    }
    system = (
        "You are an ITSM SLA at-risk assistant for SVRMON24. "
        "Respond with a single JSON object only. "
        "Keep deterministic at_risk values. Never mutate clocks or statuses. "
        "Required keys: summary (string), items (array with tracking_id, narrative, "
        "suggested_actions)."
    )
    result = ai_facade_service.safe_run_structured_task(
        task_key="itsm.sla_at_risk",
        tenant_id=tid,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": "Draft SLA at-risk assist as JSON:\n"
                + json.dumps(prompt, default=str),
            },
        ],
        fallback_builder=lambda reason: base
        if reason == "rule_based_fallback"
        else _fallback(reason),
        validate_fn=_validate_sla,
        force_fallback=force_fallback,
        record_usage=True,
    )
    if result.source in {SOURCE_OLLAMA, SOURCE_CLOUD}:
        return _normalize_sla(
            result.payload if isinstance(result.payload, dict) else {},
            fallback=base,
            source=result.source,
            model=result.model,
        )
    payload = result.payload
    if isinstance(payload, dict) and (
        payload.get("summary") is not None or payload.get("items") is not None
    ):
        if payload.get("safety"):
            return payload
        return _normalize_sla(
            payload,
            fallback=base,
            source=SOURCE_RULE,
            model=None,
        )
    return _fallback(result.fallback_reason or "rule_based_fallback")
