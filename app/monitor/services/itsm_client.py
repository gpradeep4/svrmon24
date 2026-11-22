"""ITSM boundary helpers for Monitoring — drafts + optional auto-create.

Monitoring never writes ITSM Mongo collections directly. Incident create happens
via the ITSM **service** (same shape as ``POST /api/itsm/incidents``):

* Human path: suggest draft → Apply via ITSM API.
* Auto path (L8): tenant ``monitor_auto_incident_opt_in`` + rule ``auto_incident``
  → ``create_incident_from_alert`` with actor ``monitor-auto-incident``.
"""

from __future__ import annotations

from typing import Any

# Monitor alert severity → ITSM incident priority (assist mapping).
SEVERITY_TO_PRIORITY: dict[str, str] = {
    "critical": "p1",
    "error": "p2",
    "warning": "p3",
    "info": "p4",
}

AUTO_INCIDENT_ACTOR: dict[str, str] = {
    "user_id": "monitor-auto-incident",
    "username": "monitor-auto-incident",
}


def severity_to_priority(severity: str | None) -> str:
    key = str(severity or "warning").strip().lower()
    return SEVERITY_TO_PRIORITY.get(key, "p3")


def draft_incident_from_alert(
    alert: dict[str, Any],
    *,
    auto_create: bool = False,
) -> dict[str, Any]:
    """Build an ITSM ``IncidentCreate``-shaped draft from a monitor alert.

    When ``auto_create`` is False (default), returns suggestion JSON only —
    does **not** create an incident.
    """
    severity = str(alert.get("severity") or "warning").lower()
    priority = severity_to_priority(severity)
    rule_name = alert.get("rule_name") or alert.get("rule_id") or "Monitoring alert"
    summary = (alert.get("summary") or "").strip() or "Alert fired"
    alert_id = alert.get("alert_id") or ""
    component_id = (alert.get("component_id") or "").strip() or None

    title = f"[Monitor] {rule_name}: {summary}"
    if len(title) > 500:
        title = title[:497] + "..."

    evidence = alert.get("evidence_refs") or []
    evidence_lines: list[str] = []
    for ref in evidence[:12]:
        if not isinstance(ref, dict):
            continue
        kind = ref.get("kind") or ref.get("type") or "evidence"
        bits = [f"- {kind}"]
        for key in (
            "metric_name",
            "value",
            "event_id",
            "stream_id",
            "path",
            "watch_id",
            "sample_id",
            "message",
        ):
            if ref.get(key) is not None:
                bits.append(f"{key}={ref.get(key)}")
        evidence_lines.append(" ".join(bits))

    if auto_create:
        desc_parts = [
            "Incident auto-created from Monitoring alert "
            "(tenant monitor_auto_incident_opt_in + rule.auto_incident).",
            "Actor: monitor-auto-incident. No AI auto-approve of unrelated flows.",
            "",
        ]
    else:
        desc_parts = [
            "Draft incident suggested from Monitoring alert.",
            "Human must Apply via ITSM — Monitoring does not auto-create "
            "unless tenant opt-in + rule.auto_incident (L8).",
            "",
        ]
    desc_parts.extend(
        [
            f"Alert ID: {alert_id}",
            f"Rule: {rule_name}",
            f"Severity: {severity}",
            f"Status: {alert.get('status') or '—'}",
            f"Summary: {summary}",
        ]
    )
    if component_id:
        desc_parts.append(f"Component ID: {component_id}")
    if alert.get("target_id"):
        desc_parts.append(f"Target ID: {alert.get('target_id')}")
    if alert.get("fired_at"):
        desc_parts.append(f"Fired at: {alert.get('fired_at')}")
    if evidence_lines:
        desc_parts.append("")
        desc_parts.append("Evidence:")
        desc_parts.extend(evidence_lines)

    description = "\n".join(desc_parts)
    if len(description) > 20000:
        description = description[:19997] + "..."

    ci_links: list[dict[str, str]] = []
    if component_id:
        ci_links.append({"component_id": component_id})

    return {
        "title": title,
        "description": description,
        "severity": severity,
        "priority": priority,
        "ci_links": ci_links,
        "category": "monitoring",
        "source": "rule_based_fallback",
        "alert_id": alert_id,
        "suggested_incident_id": alert.get("suggested_incident_id"),
        "apply_via": "POST /api/itsm/incidents",
        "auto_create": bool(auto_create),
        "notice": (
            "Auto-created via ITSM service (actor=monitor-auto-incident)."
            if auto_create
            else (
                "Draft only. Creating an incident requires itsm:incident:write "
                "and an explicit user Apply action — or tenant auto-incident "
                "opt-in with rule.auto_incident (L8). Monitoring never writes "
                "ITSM Mongo directly."
            )
        ),
    }


def create_incident_from_alert(
    alert: dict[str, Any],
    *,
    tenant_id: str,
) -> dict[str, Any]:
    """Create an ITSM incident via the ITSM service client (no cross-DB write).

    Uses the same ``IncidentCreate`` shape as human Apply. Actor is the
    Monitoring system principal ``monitor-auto-incident``.
    """
    from ...itsm.models.incidents import IncidentCreate
    from ...itsm.services import incidents as incidents_service

    draft = draft_incident_from_alert(alert, auto_create=True)
    payload = IncidentCreate(
        title=draft["title"],
        description=draft.get("description"),
        priority=draft.get("priority") or "p3",
        category=draft.get("category") or "monitoring",
        ci_links=draft.get("ci_links") or [],
    )
    return incidents_service.create_incident(
        payload,
        tenant_id=tenant_id,
        actor=dict(AUTO_INCIDENT_ACTOR),
    )
