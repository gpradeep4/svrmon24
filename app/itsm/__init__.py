"""ITSM module — dual-DB (``svrmon-itsm``), isolated from CMDB collections.

Cross-access to CMDB is via component / entity-ref services only — no joins.
"""

from __future__ import annotations

ITSM_COLLECTIONS: tuple[str, ...] = (
    "itsm_incidents",
    "itsm_changes",
    "itsm_problems",
    "itsm_ticket_activities",
    "itsm_counters",
    "itsm_approvals",
    "itsm_workflows",
    "itsm_workflow_executions",
    "itsm_sla_policies",
    "itsm_sla_tracking",
    "itsm_knowledge_articles",
    "itsm_notifications",
)
