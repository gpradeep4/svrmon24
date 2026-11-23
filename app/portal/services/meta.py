"""Service Portal module metadata — SIMULATED default; live gates fail-closed."""

from __future__ import annotations

from typing import Any

from ...config import Settings, get_settings
from .. import PORTAL_COLLECT_MODES, PORTAL_COLLECTIONS, PORTAL_DOMAINS

EXECUTION_MODE = "SIMULATED"
DATA_SOURCE = "SYNTHETIC_DEMO"
BANNER_SIMULATED = (
    "SIMULATED — platform SERVICE_PORTAL_LIVE_EXEC_ENABLED and/or tenant "
    "sp_live_opt_in are off (fail-closed). Catalog requests may be approved and "
    "run as synthetic executions until both gates are on. Collect modes "
    "AGENTLESS and AGENT are modeled; live adapters stay stubbed."
)


def live_gates() -> dict[str, Any]:
    """Effective live-gate snapshot (fail-closed; SP0 always reports off).

    SP9 wires platform Settings + tenant opt-in; until then every live path is off.
    """
    return {
        "platform_enabled": False,
        "tenant_opt_in": False,
        "agentless_enabled": False,
        "agent_enabled": False,
        "live_exec": False,
        "fail_closed": True,
    }


def module_meta(
    *,
    settings: Settings | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Tenant-aware Service Portal meta payload."""
    cfg = settings or get_settings()
    gates = live_gates()
    return {
        "module": "service_portal",
        "execution_mode": EXECUTION_MODE,
        "data_source": DATA_SOURCE,
        "demo_only": True,
        "live_exec": False,
        "live_gates": gates,
        "collect_modes": list(PORTAL_COLLECT_MODES),
        "domains": list(PORTAL_DOMAINS),
        "banner": BANNER_SIMULATED,
        "database": cfg.itsm_database_name,
        "itsm_database": cfg.itsm_database_name,
        "collections": list(PORTAL_COLLECTIONS),
        "cmdb_sync": True,
        "agent_channel": "monitoring",
        "tenant_id": tenant_id,
    }
