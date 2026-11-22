"""Monitoring module — dedicated DB (``svrmon-monitor``), isolated from CMDB/ITSM.

Cross-access to CMDB/ITSM is via service/API clients only — no joins.
SIMULATED remains the default; live paths are fail-closed behind platform
``MONITOR_LIVE_PROBES_ENABLED`` + per-tenant ``monitor_live_opt_in``.
"""

from __future__ import annotations

# M3: File Monitoring. M4: targets + metric samples. M5: log streams/events.
# M6: alert rules + instances. M7: dashboard aggregates + suggest-incident.
# M8: diagnostics history rehome + retention sweeper.
# L0: live gates + meta + model widenings (no real polls yet).
MONITOR_COLLECTIONS: tuple[str, ...] = (
    "file_watch_targets",
    "file_version_events",
    "monitor_targets",
    "metric_samples",
    "log_streams",
    "log_events",
    "monitor_simulate_ticks",
    "alert_rules",
    "alert_instances",
    "diagnostic_history",
)
