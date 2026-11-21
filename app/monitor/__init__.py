"""Monitoring module — dedicated DB (``svrmon-monitor``), isolated from CMDB/ITSM.

Cross-access to CMDB/ITSM is via service/API clients only — no joins.
v1 is SIMULATED-only (``live_probes: false``); live agents require separate approval.
"""

from __future__ import annotations

# Collections land in later slices (M3+). M0 is package + meta scaffolding only.
MONITOR_COLLECTIONS: tuple[str, ...] = ()
