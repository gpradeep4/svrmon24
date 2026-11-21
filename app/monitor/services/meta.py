"""Monitoring module metadata — SIMULATED v1 (no live probes)."""

from __future__ import annotations

from typing import Any

from ...config import Settings, get_settings

EXECUTION_MODE = "SIMULATED"
DATA_SOURCE = "SYNTHETIC_DEMO"
# Product lock: both collect modes in model/meta from day one; live still gated.
COLLECT_MODES: tuple[str, ...] = ("agentless", "agent")
OS_FAMILIES: tuple[str, ...] = ("linux", "windows", "macos", "unix")
NETWORK_TARGET_KINDS: tuple[str, ...] = (
    "switch",
    "router",
    "firewall",
    "load_balancer",
    "access_point",
    "other_network",
)
DOMAINS: tuple[str, ...] = ("server", "network", "application", "database")
BANNER = (
    "SIMULATED / SYNTHETIC_DEMO — Monitoring does not run live probes or agents. "
    "Target health, metric samples, and log streams are synthetic; live probes stay off."
)


def module_meta(*, settings: Settings | None = None) -> dict[str, Any]:
    """Stable meta payload for ``GET /api/monitor/meta``."""
    cfg = settings or get_settings()
    return {
        "module": "monitoring",
        "execution_mode": EXECUTION_MODE,
        "data_source": DATA_SOURCE,
        "demo_only": True,
        "live_probes": False,
        "collect_modes": list(COLLECT_MODES),
        "domains": list(DOMAINS),
        "os_families": list(OS_FAMILIES),
        "network_target_kinds": list(NETWORK_TARGET_KINDS),
        "banner": BANNER,
        "notice": (
            "Monitoring v1 is SIMULATED. Sync targets from CMDB (API client only); "
            "domain health views stamp AGENTLESS/AGENT collect modes for all OS "
            "families and networking kinds. Log streams are searchable synthetic "
            "events (no live syslog ingest); simulate-tick is admin-only. Live "
            "probes stay off until explicitly approved. File Monitoring and "
            "Diagnostics stay under Monitoring (CMDB keeps temporary redirects)."
        ),
        "log_sources": ["agentless", "agent", "simulated"],
        "log_severities": [
            "debug",
            "info",
            "warning",
            "error",
            "critical",
        ],
        "database": cfg.monitor_database_name,
        "monitor_database": cfg.monitor_database_name,
    }
