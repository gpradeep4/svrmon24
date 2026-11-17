"""ITSM module — dual-DB (``svrmon-itsm``), isolated from CMDB collections.

Cross-access to CMDB is via component / entity-ref services only — no joins.
"""

from __future__ import annotations

ITSM_COLLECTIONS: tuple[str, ...] = (
    "itsm_incidents",
    "itsm_ticket_activities",
    "itsm_counters",
)
