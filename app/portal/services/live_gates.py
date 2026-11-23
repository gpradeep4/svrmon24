"""Service Portal live gates — fail-closed unless platform + tenant allow (SP9).

SIMULATED catalog / requests / simulate-tick ignore these flags.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException

from ...config import Settings, get_settings
from ...services import tenants as tenants_service

LiveCapability = Literal["live_exec", "agentless", "agent"]

LIVE_DISABLED_DETAIL = (
    "Service Portal LIVE execution is disabled (platform and/or tenant gate). "
    "SIMULATED paths remain available."
)


def _tenant_doc(tenant_id: str) -> dict[str, Any]:
    doc = tenants_service.get_tenant(tenant_id) or {}
    return doc if isinstance(doc, dict) else {}


def tenant_live_settings(tenant_id: str) -> dict[str, Any]:
    doc = _tenant_doc(tenant_id)
    return {
        "sp_live_opt_in": bool(doc.get("sp_live_opt_in")),
        "sp_live_agentless_opt_in": bool(doc.get("sp_live_agentless_opt_in")),
        "sp_live_agent_opt_in": bool(doc.get("sp_live_agent_opt_in")),
    }


def live_gates(
    *,
    tenant_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Effective live-gate snapshot for meta + admin."""
    cfg = settings or get_settings()
    platform_on = bool(cfg.service_portal_live_exec_enabled)
    tenant = (
        tenant_live_settings(tenant_id)
        if tenant_id
        else {
            "sp_live_opt_in": False,
            "sp_live_agentless_opt_in": False,
            "sp_live_agent_opt_in": False,
        }
    )
    tenant_on = bool(tenant["sp_live_opt_in"])
    master = platform_on and tenant_on
    allowlist = (cfg.service_portal_egress_allowlist or "").strip()
    return {
        "platform_enabled": platform_on,
        "tenant_opt_in": tenant_on,
        "agentless_enabled": master
        and bool(cfg.service_portal_live_agentless_enabled)
        and bool(tenant["sp_live_agentless_opt_in"]),
        "agent_enabled": master
        and bool(cfg.service_portal_live_agent_enabled)
        and bool(tenant["sp_live_agent_opt_in"]),
        "live_exec": master,
        "fail_closed": True,
        "egress_allowlist_configured": bool(allowlist),
        # SP10 / SM-166 — live adapters unlocked; still fail-closed on gates.
        "live_adapters": True,
    }


def assert_live_allowed(
    *,
    tenant_id: str,
    capability: LiveCapability = "live_exec",
    settings: Settings | None = None,
) -> None:
    """Raise 403 unless the requested live capability is fully gated open."""
    gates = live_gates(tenant_id=tenant_id, settings=settings)
    ok = False
    if capability == "live_exec":
        ok = bool(gates["live_exec"])
    elif capability == "agentless":
        ok = bool(gates["agentless_enabled"])
    elif capability == "agent":
        ok = bool(gates["agent_enabled"])
    if not ok:
        raise HTTPException(status_code=403, detail=LIVE_DISABLED_DETAIL)


def live_exec_effective(*, tenant_id: str, settings: Settings | None = None) -> bool:
    return bool(live_gates(tenant_id=tenant_id, settings=settings)["live_exec"])
