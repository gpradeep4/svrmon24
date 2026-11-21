"""ITSM boundary helpers for Monitoring — draft payloads only.

Monitoring never writes ITSM collections. Incident create happens only when
the human applies a draft via the ITSM API (``POST /api/itsm/incidents``).
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


def severity_to_priority(severity: str | None) -> str:
    key = str(severity or "warning").strip().lower()
    return SEVERITY_TO_PRIORITY.get(key, "p3")


def draft_incident_from_alert(alert: dict[str, Any]) -> dict[str, Any]:
    """Build an ITSM ``IncidentCreate``-shaped draft from a monitor alert.

    Returns suggestion JSON only — does **not** create an incident.
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

    desc_parts = [
        "Draft incident suggested from Monitoring alert (SIMULATED).",
        "Human must Apply via ITSM — Monitoring does not auto-create tickets.",
        "",
        f"Alert ID: {alert_id}",
        f"Rule: {rule_name}",
        f"Severity: {severity}",
        f"Status: {alert.get('status') or '—'}",
        f"Summary: {summary}",
    ]
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
        "auto_create": False,
        "notice": (
            "Draft only. Creating an incident requires itsm:incident:write "
            "and an explicit user Apply action — Monitoring never writes ITSM."
        ),
    }
