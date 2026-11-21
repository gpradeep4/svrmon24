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
BANNER = (
    "SIMULATED / SYNTHETIC_DEMO — Monitoring does not run live probes or agents. "
    "Synthetic metrics, logs, and alerts will appear in later slices."
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
        "os_families": list(OS_FAMILIES),
        "network_target_kinds": list(NETWORK_TARGET_KINDS),
        "banner": BANNER,
        "notice": (
            "Monitoring v1 is SIMULATED. Data model supports AGENTLESS and AGENT "
            "collect modes for all OS families and networking components, but live "
            "probes stay off until explicitly approved. File Monitoring and "
            "Diagnostics move under Monitoring in later slices."
        ),
        "database": cfg.monitor_database_name,
        "monitor_database": cfg.monitor_database_name,
    }
