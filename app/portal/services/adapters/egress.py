"""Portal egress allowlist — reuses Monitoring egress helpers with SP env."""

from __future__ import annotations

from typing import Any

from ....config import Settings, get_settings
from ....monitor.services.egress import (
    EgressDenied,
    assert_egress_allowed,
    parse_allowlist,
)


def portal_egress_status(*, settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    entries = parse_allowlist(cfg.service_portal_egress_allowlist or "")
    return {
        "env_var": "SERVICE_PORTAL_EGRESS_ALLOWLIST",
        "configured": bool(entries),
        "entry_count": len(entries),
        "entries": entries,
        "deny_all_when_empty": True,
    }


def assert_portal_egress(
    *,
    hostname: str,
    settings: Settings | None = None,
) -> list[str]:
    cfg = settings or get_settings()
    try:
        return assert_egress_allowed(
            hostname=hostname,
            platform_allowlist=cfg.service_portal_egress_allowlist or "",
        )
    except EgressDenied as exc:
        # Rewrite message to name the portal env var.
        msg = exc.message.replace(
            "MONITOR_EGRESS_ALLOWLIST", "SERVICE_PORTAL_EGRESS_ALLOWLIST"
        )
        raise EgressDenied(msg) from exc


__all__ = ["EgressDenied", "assert_portal_egress", "portal_egress_status"]
