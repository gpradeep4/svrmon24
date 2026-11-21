"""Monitoring module — dedicated DB (``svrmon-monitor``), isolated from CMDB/ITSM.

Cross-access to CMDB/ITSM is via service/API clients only — no joins.
v1 is SIMULATED-only (``live_probes: false``); live agents require separate approval.
"""

from __future__ import annotations

# M3: File Monitoring. M4: targets + metric samples. M5: log streams/events.
# M6: alert rules + instances.
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
)
