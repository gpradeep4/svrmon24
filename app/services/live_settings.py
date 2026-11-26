"""Unified live / runtime gates across modules (fail-closed).

Reuses Monitoring + Service Portal gate helpers; adds Diagnostics and ITSM
automation masters. Tenant toggles live on the tenant document; platform
masters stay env-only.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..config import Settings, get_settings
from ..monitor.services import live_gates as monitor_gates
from ..portal.services import live_gates as portal_gates
from . import tenants as tenants_service

DIAGNOSTICS_LIVE_DISABLED = (
    "Diagnostics LIVE is disabled (platform and/or tenant gate). "
    "SIMULATED diagnostics remain available."
)
ITSM_AUTOMATION_DISABLED = (
    "ITSM automation is disabled (platform and/or tenant gate). "
    "Manual workflows and ticket CRUD remain available."
)

# Tenant fields accepted by the unified PATCH (plus retention tier).
UNIFIED_TENANT_BOOL_FIELDS: frozenset[str] = frozenset(
    {
        "monitor_live_opt_in",
        "monitor_live_agentless_opt_in",
        "monitor_live_agent_opt_in",
        "monitor_auto_incident_opt_in",
        "sp_live_opt_in",
        "sp_live_agentless_opt_in",
        "sp_live_agent_opt_in",
        "diagnostics_live_opt_in",
        "itsm_automation_opt_in",
    }
)


def _tenant_doc(tenant_id: str) -> dict[str, Any]:
    doc = tenants_service.get_tenant(tenant_id) or {}
    return doc if isinstance(doc, dict) else {}


def diagnostics_tenant_settings(tenant_id: str) -> dict[str, Any]:
    doc = _tenant_doc(tenant_id)
    return {"diagnostics_live_opt_in": bool(doc.get("diagnostics_live_opt_in"))}


def itsm_tenant_settings(tenant_id: str) -> dict[str, Any]:
    doc = _tenant_doc(tenant_id)
    return {"itsm_automation_opt_in": bool(doc.get("itsm_automation_opt_in"))}


def diagnostics_live_gates(
    *, tenant_id: str, settings: Settings | None = None
) -> dict[str, Any]:
    cfg = settings or get_settings()
    tenant = diagnostics_tenant_settings(tenant_id)
    platform_on = bool(cfg.diagnostics_live_enabled)
    tenant_on = bool(tenant["diagnostics_live_opt_in"])
    return {
        "platform_enabled": platform_on,
        "tenant_opt_in": tenant_on,
        "live_exec": platform_on and tenant_on,
        "fail_closed": True,
    }


def itsm_automation_gates(
    *, tenant_id: str, settings: Settings | None = None
) -> dict[str, Any]:
    cfg = settings or get_settings()
    tenant = itsm_tenant_settings(tenant_id)
    platform_on = bool(cfg.itsm_automation_enabled)
    tenant_on = bool(tenant["itsm_automation_opt_in"])
    return {
        "platform_enabled": platform_on,
        "tenant_opt_in": tenant_on,
        "automation": platform_on and tenant_on,
        "fail_closed": True,
    }


def diagnostics_live_allowed(
    *, tenant_id: str, settings: Settings | None = None
) -> bool:
    return bool(
        diagnostics_live_gates(tenant_id=tenant_id, settings=settings)["live_exec"]
    )


def assert_diagnostics_live(
    *, tenant_id: str, settings: Settings | None = None
) -> None:
    if not diagnostics_live_allowed(tenant_id=tenant_id, settings=settings):
        raise HTTPException(status_code=403, detail=DIAGNOSTICS_LIVE_DISABLED)


def itsm_automation_allowed(
    *, tenant_id: str, settings: Settings | None = None
) -> bool:
    return bool(
        itsm_automation_gates(tenant_id=tenant_id, settings=settings)["automation"]
    )


def unified_live_settings(
    *, tenant_id: str, settings: Settings | None = None
) -> dict[str, Any]:
    """Aggregate platform + tenant + effective gates for Configuration UI."""
    cfg = settings or get_settings()
    monitor_tenant = monitor_gates.tenant_live_settings(tenant_id)
    monitor_effective = monitor_gates.live_gates(tenant_id=tenant_id, settings=cfg)
    portal_tenant = portal_gates.tenant_live_settings(tenant_id)
    portal_effective = portal_gates.live_gates(tenant_id=tenant_id, settings=cfg)
    diag_tenant = diagnostics_tenant_settings(tenant_id)
    diag_effective = diagnostics_live_gates(tenant_id=tenant_id, settings=cfg)
    itsm_tenant = itsm_tenant_settings(tenant_id)
    itsm_effective = itsm_automation_gates(tenant_id=tenant_id, settings=cfg)

    file_watch_effective = bool(
        monitor_gates.live_allowed(
            tenant_id=tenant_id, capability="file_watch_live", settings=cfg
        )
    )

    return {
        "tenant_id": tenant_id,
        "fail_closed": True,
        "modules": {
            "monitoring": {
                "label": "Monitoring live probes",
                "description": (
                    "Agentless polls, agent ingest, syslog, and live stubs. "
                    "SIMULATED paths stay available when off."
                ),
                "platform": {
                    "MONITOR_LIVE_PROBES_ENABLED": bool(cfg.monitor_live_probes_enabled),
                    "MONITOR_LIVE_AGENTLESS_ENABLED": bool(
                        cfg.monitor_live_agentless_enabled
                    ),
                    "MONITOR_LIVE_AGENT_ENABLED": bool(cfg.monitor_live_agent_enabled),
                    "MONITOR_LIVE_HTTP_INGEST_ENABLED": bool(
                        cfg.monitor_live_http_ingest_enabled
                    ),
                    "MONITOR_POLLER_ENABLED": bool(cfg.monitor_poller_enabled),
                    "MONITOR_EGRESS_ALLOWLIST_SET": bool(
                        (cfg.monitor_egress_allowlist or "").strip()
                    ),
                },
                "tenant": monitor_tenant,
                "effective": monitor_effective,
                "toggles": [
                    {
                        "key": "monitor_live_opt_in",
                        "label": "Enable Monitoring live",
                        "value": bool(monitor_tenant["monitor_live_opt_in"]),
                    },
                    {
                        "key": "monitor_live_agentless_opt_in",
                        "label": "Agentless polls",
                        "value": bool(monitor_tenant["monitor_live_agentless_opt_in"]),
                    },
                    {
                        "key": "monitor_live_agent_opt_in",
                        "label": "Agent register / ingest",
                        "value": bool(monitor_tenant["monitor_live_agent_opt_in"]),
                    },
                    {
                        "key": "monitor_auto_incident_opt_in",
                        "label": "Auto-create ITSM incidents from alerts",
                        "value": bool(monitor_tenant["monitor_auto_incident_opt_in"]),
                    },
                ],
            },
            "file_watchers": {
                "label": "File watchers (live)",
                "description": (
                    "AGENT / AGENTLESS_POLL file watching. Uses Monitoring "
                    "platform + tenant agent/agentless gates."
                ),
                "platform": {
                    "MONITOR_LIVE_PROBES_ENABLED": bool(cfg.monitor_live_probes_enabled),
                    "MONITOR_LIVE_AGENTLESS_ENABLED": bool(
                        cfg.monitor_live_agentless_enabled
                    ),
                    "MONITOR_LIVE_AGENT_ENABLED": bool(cfg.monitor_live_agent_enabled),
                },
                "tenant": {
                    "monitor_live_opt_in": bool(monitor_tenant["monitor_live_opt_in"]),
                    "monitor_live_agentless_opt_in": bool(
                        monitor_tenant["monitor_live_agentless_opt_in"]
                    ),
                    "monitor_live_agent_opt_in": bool(
                        monitor_tenant["monitor_live_agent_opt_in"]
                    ),
                },
                "effective": {
                    "file_watch_live": file_watch_effective,
                    "fail_closed": True,
                },
                "toggles": [
                    {
                        "key": "monitor_live_opt_in",
                        "label": "Enable Monitoring live (required)",
                        "value": bool(monitor_tenant["monitor_live_opt_in"]),
                    },
                    {
                        "key": "monitor_live_agent_opt_in",
                        "label": "Agent file events",
                        "value": bool(monitor_tenant["monitor_live_agent_opt_in"]),
                    },
                    {
                        "key": "monitor_live_agentless_opt_in",
                        "label": "Agentless file poll",
                        "value": bool(monitor_tenant["monitor_live_agentless_opt_in"]),
                    },
                ],
            },
            "portal": {
                "label": "Service Portal live execute",
                "description": (
                    "Catalog LIVE execute after Change approval. "
                    "SIMULATED / DRY_RUN remain when off."
                ),
                "platform": {
                    "SERVICE_PORTAL_LIVE_EXEC_ENABLED": bool(
                        cfg.service_portal_live_exec_enabled
                    ),
                    "SERVICE_PORTAL_LIVE_AGENTLESS_ENABLED": bool(
                        cfg.service_portal_live_agentless_enabled
                    ),
                    "SERVICE_PORTAL_LIVE_AGENT_ENABLED": bool(
                        cfg.service_portal_live_agent_enabled
                    ),
                    "SERVICE_PORTAL_EGRESS_ALLOWLIST_SET": bool(
                        (cfg.service_portal_egress_allowlist or "").strip()
                    ),
                },
                "tenant": portal_tenant,
                "effective": portal_effective,
                "toggles": [
                    {
                        "key": "sp_live_opt_in",
                        "label": "Enable Portal live execute",
                        "value": bool(portal_tenant["sp_live_opt_in"]),
                    },
                    {
                        "key": "sp_live_agentless_opt_in",
                        "label": "Portal agentless",
                        "value": bool(portal_tenant["sp_live_agentless_opt_in"]),
                    },
                    {
                        "key": "sp_live_agent_opt_in",
                        "label": "Portal agent",
                        "value": bool(portal_tenant["sp_live_agent_opt_in"]),
                    },
                ],
            },
            "diagnostics": {
                "label": "Diagnostics live",
                "description": (
                    "Optional LIVE diagnostic runs (agentless connectivity). "
                    "SIMULATED profiles always remain available."
                ),
                "platform": {
                    "DIAGNOSTICS_LIVE_ENABLED": bool(cfg.diagnostics_live_enabled),
                },
                "tenant": diag_tenant,
                "effective": diag_effective,
                "toggles": [
                    {
                        "key": "diagnostics_live_opt_in",
                        "label": "Enable Diagnostics live",
                        "value": bool(diag_tenant["diagnostics_live_opt_in"]),
                    },
                ],
            },
            "itsm_automation": {
                "label": "ITSM automation",
                "description": (
                    "Workflow auto-triggers (on_create / on_status / schedule). "
                    "Manual workflow start and ticket CRUD stay available when off."
                ),
                "platform": {
                    "ITSM_AUTOMATION_ENABLED": bool(cfg.itsm_automation_enabled),
                    "ITSM_JOB_RUNNER_ENABLED": bool(cfg.itsm_job_runner_enabled),
                },
                "tenant": itsm_tenant,
                "effective": itsm_effective,
                "toggles": [
                    {
                        "key": "itsm_automation_opt_in",
                        "label": "Enable ITSM automation",
                        "value": bool(itsm_tenant["itsm_automation_opt_in"]),
                    },
                ],
            },
        },
        "legacy_endpoints": {
            "monitoring": "/api/monitor/admin/live-settings",
            "portal": "/api/portal/admin/live-settings",
            "unified": "/api/admin/live-settings",
        },
        "note": (
            "Live paths are fail-closed: platform env masters default off, and "
            "tenant admins must opt in here. Non-admins cannot change toggles."
        ),
    }


def apply_unified_live_settings(
    tenant_id: str, updates: dict[str, Any]
) -> dict[str, Any]:
    """Patch any combination of tenant live fields; returns refreshed snapshot."""
    monitor_keys = {
        "monitor_live_opt_in",
        "monitor_live_agentless_opt_in",
        "monitor_live_agent_opt_in",
        "monitor_auto_incident_opt_in",
        "monitor_retention_tier",
    }
    portal_keys = {
        "sp_live_opt_in",
        "sp_live_agentless_opt_in",
        "sp_live_agent_opt_in",
    }
    extra_keys = {"diagnostics_live_opt_in", "itsm_automation_opt_in"}

    monitor_updates = {k: v for k, v in updates.items() if k in monitor_keys}
    portal_updates = {k: v for k, v in updates.items() if k in portal_keys}
    extra_updates = {k: v for k, v in updates.items() if k in extra_keys}

    if not monitor_updates and not portal_updates and not extra_updates:
        raise tenants_service.TenantError(
            "No valid live settings fields to update", status_code=400
        )

    if monitor_updates:
        tenants_service.set_monitor_live_settings(tenant_id, monitor_updates)
    if portal_updates:
        tenants_service.set_portal_live_settings(tenant_id, portal_updates)
    if extra_updates:
        tenants_service.set_module_live_settings(tenant_id, extra_updates)

    return unified_live_settings(tenant_id=tenant_id)
