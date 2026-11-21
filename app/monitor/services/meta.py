"""Monitoring module metadata — SIMULATED v1 (no live probes)."""

from __future__ import annotations

from typing import Any

from ...config import Settings, get_settings

EXECUTION_MODE = "SIMULATED"
DATA_SOURCE = "SYNTHETIC_DEMO"
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
        "banner": BANNER,
        "notice": (
            "Monitoring v1 is SIMULATED. Live probes and agents stay off until "
            "explicitly approved. File Monitoring and Diagnostics move under "
            "Monitoring in later slices."
        ),
        "database": cfg.monitor_database_name,
        "monitor_database": cfg.monitor_database_name,
    }
