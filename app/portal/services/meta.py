"""Service Portal module metadata — SIMULATED default; live gates fail-closed."""

from __future__ import annotations

from typing import Any

from ...config import Settings, get_settings
from .. import PORTAL_COLLECT_MODES, PORTAL_COLLECTIONS, PORTAL_DOMAINS
from . import live_gates as live_gates_service

EXECUTION_MODE = "SIMULATED"
DATA_SOURCE = "SYNTHETIC_DEMO"
BANNER_SIMULATED = (
    "SIMULATED — platform SERVICE_PORTAL_LIVE_EXEC_ENABLED and/or tenant "
    "sp_live_opt_in are off (fail-closed). Catalog requests may be approved and "
    "run as synthetic executions until both gates are on. Collect modes "
    "AGENTLESS and AGENT are available; LIVE adapters unlock when both gates "
    "are on (Cloud provision uses Terraform)."
)
BANNER_LIVE = (
    "LIVE gates open — AGENT / AGENTLESS adapters enabled for allowlisted "
    "actions. Cloud VM provision uses Terraform. DRY_RUN remains plan-only."
)


def live_gates(*, tenant_id: str | None = None) -> dict[str, Any]:
    """Effective live-gate snapshot (SP9)."""
    return live_gates_service.live_gates(tenant_id=tenant_id)


def module_meta(
    *,
    settings: Settings | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Tenant-aware Service Portal meta payload."""
    cfg = settings or get_settings()
    gates = live_gates(tenant_id=tenant_id)
    live_on = bool(gates.get("live_exec"))
    return {
        "module": "service_portal",
        "execution_mode": "LIVE" if live_on else EXECUTION_MODE,
        "data_source": DATA_SOURCE if not live_on else "LIVE_GATED",
        "demo_only": not live_on,
        "live_exec": live_on,
        "live_gates": gates,
        "collect_modes": list(PORTAL_COLLECT_MODES),
        "domains": list(PORTAL_DOMAINS),
        "banner": BANNER_LIVE if live_on else BANNER_SIMULATED,
        "database": cfg.itsm_database_name,
        "itsm_database": cfg.itsm_database_name,
        "collections": list(PORTAL_COLLECTIONS),
        "cmdb_sync": True,
        "agent_channel": "monitoring",
        "cloud_provision": "terraform",
        "tenant_id": tenant_id,
        "live_adapters": True,
    }
