"""Monitoring module — dedicated DB (``svrmon-monitor``), isolated from CMDB/ITSM.

Cross-access to CMDB/ITSM is via service/API clients only — no joins.
v1 is SIMULATED-only (``live_probes: false``); live agents require separate approval.
"""

from __future__ import annotations

# M3: File Monitoring. M4: targets + metric samples. Later: logs/alerts.
MONITOR_COLLECTIONS: tuple[str, ...] = (
    "file_watch_targets",
    "file_version_events",
    "monitor_targets",
    "metric_samples",
)
