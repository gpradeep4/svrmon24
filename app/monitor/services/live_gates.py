"""Platform + tenant live gates — fail-closed unless both sides allow.

SIMULATED seed / simulate-tick / banners ignore these flags.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException

from ...config import Settings, get_settings
from ...services import tenants as tenants_service

LiveCapability = Literal[
    "agentless_poll",
    "log_ingest_http",
    "log_ingest_syslog",
    "agent_register",
    "agent_ingest",
    "file_watch_live",
    "auto_incident",
    "live_stub",
]

LIVE_DISABLED_DETAIL = (
    "Live monitoring is disabled (platform and/or tenant gate). "
    "SIMULATED paths remain available."
)


def _tenant_doc(tenant_id: str) -> dict[str, Any]:
    doc = tenants_service.get_tenant(tenant_id) or {}
    return doc if isinstance(doc, dict) else {}


def tenant_live_settings(tenant_id: str) -> dict[str, Any]:
    """Normalized tenant live opt-in fields (defaults false / hot)."""
    doc = _tenant_doc(tenant_id)
    tier = str(doc.get("monitor_retention_tier") or "hot").strip().lower()
    if tier not in {"hot", "extended", "siem"}:
        tier = "hot"
    return {
        "monitor_live_opt_in": bool(doc.get("monitor_live_opt_in")),
        "monitor_live_agentless_opt_in": bool(doc.get("monitor_live_agentless_opt_in")),
        "monitor_live_agent_opt_in": bool(doc.get("monitor_live_agent_opt_in")),
        "monitor_auto_incident_opt_in": bool(doc.get("monitor_auto_incident_opt_in")),
        "monitor_retention_tier": tier,
    }


def live_gates(
    *,
    tenant_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Effective gate chips for meta + admin (additive surface)."""
    cfg = settings or get_settings()
    tenant = tenant_live_settings(tenant_id)
    platform_on = bool(cfg.monitor_live_probes_enabled)
    tenant_on = bool(tenant["monitor_live_opt_in"])
    master = platform_on and tenant_on
    syslog_bound = bool((cfg.monitor_live_syslog_bind or "").strip()) and master
    return {
        "platform_enabled": platform_on,
        "tenant_opt_in": tenant_on,
        "agentless": master
        and bool(cfg.monitor_live_agentless_enabled)
        and bool(tenant["monitor_live_agentless_opt_in"]),
        "agent": master
        and bool(cfg.monitor_live_agent_enabled)
        and bool(tenant["monitor_live_agent_opt_in"]),
        "auto_incident": master and bool(tenant["monitor_auto_incident_opt_in"]),
        "syslog_bound": syslog_bound,
        "poller_enabled": master and bool(cfg.monitor_poller_enabled),
        "http_ingest": master and bool(cfg.monitor_live_http_ingest_enabled),
    }


def live_probes_effective(
    *,
    tenant_id: str,
    settings: Settings | None = None,
) -> bool:
    """True only when platform master + tenant ``monitor_live_opt_in`` are on."""
    gates = live_gates(tenant_id=tenant_id, settings=settings)
    return bool(gates["platform_enabled"] and gates["tenant_opt_in"])


def live_allowed(
    *,
    tenant_id: str,
    capability: LiveCapability,
    settings: Settings | None = None,
) -> bool:
    """Capability gate: platform master + tenant opt-in + capability flags."""
    cfg = settings or get_settings()
    if not bool(cfg.monitor_live_probes_enabled):
        return False
    tenant = tenant_live_settings(tenant_id)
    if not tenant["monitor_live_opt_in"]:
        return False

    if capability == "live_stub":
        return True
    if capability == "agentless_poll":
        return bool(cfg.monitor_live_agentless_enabled) and bool(
            tenant["monitor_live_agentless_opt_in"]
        )
    if capability == "log_ingest_http":
        return bool(cfg.monitor_live_http_ingest_enabled)
    if capability == "log_ingest_syslog":
        return bool((cfg.monitor_live_syslog_bind or "").strip()) and bool(
            cfg.monitor_live_agentless_enabled
        )
    if capability in {"agent_register", "agent_ingest", "file_watch_live"}:
        # file_watch_live via agent path for L0 gate matrix
        if capability == "file_watch_live":
            return (
                bool(cfg.monitor_live_agent_enabled)
                and bool(tenant["monitor_live_agent_opt_in"])
            ) or (
                bool(cfg.monitor_live_agentless_enabled)
                and bool(tenant["monitor_live_agentless_opt_in"])
            )
        return bool(cfg.monitor_live_agent_enabled) and bool(
            tenant["monitor_live_agent_opt_in"]
        )
    if capability == "auto_incident":
        return bool(tenant["monitor_auto_incident_opt_in"])
    return False


def require_live_capability(
    *,
    tenant_id: str,
    capability: LiveCapability,
    settings: Settings | None = None,
) -> None:
    """Raise HTTP 403 when the live capability is not allowed (fail-closed)."""
    if not live_allowed(
        tenant_id=tenant_id, capability=capability, settings=settings
    ):
        raise HTTPException(status_code=403, detail=LIVE_DISABLED_DETAIL)
