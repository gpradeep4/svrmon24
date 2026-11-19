"""Light ITSM dashboard aggregates (ITSM DB)."""

from __future__ import annotations

from typing import Any

from ...db import require_itsm_database
from ...tenancy import require_tenant_id, tenant_filter
from .indexes import CHANGES, INCIDENTS, PROBLEMS, ensure_itsm_indexes


def summary(*, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    ensure_itsm_indexes()
    itsm = require_itsm_database()
    inc = itsm[INCIDENTS]
    chg = itsm[CHANGES]
    prb = itsm[PROBLEMS]
    base = tenant_filter(tid)

    open_inc_statuses = ["new", "in_progress", "on_hold"]
    open_chg_statuses = [
        "draft",
        "submitted",
        "approved",
        "scheduled",
        "implementing",
        "review",
    ]
    open_prb_statuses = ["new", "under_investigation", "known_error"]

    open_incidents = inc.count_documents({**base, "status": {"$in": open_inc_statuses}})
    open_changes = chg.count_documents({**base, "status": {"$in": open_chg_statuses}})
    open_problems = prb.count_documents({**base, "status": {"$in": open_prb_statuses}})

    by_status: dict[str, int] = {}
    for row in inc.aggregate(
        [
            {"$match": base},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
    ):
        by_status[str(row["_id"])] = int(row["count"])

    by_priority: dict[str, int] = {}
    for row in inc.aggregate(
        [
            {"$match": {**base, "status": {"$in": open_inc_statuses}}},
            {"$group": {"_id": "$priority", "count": {"$sum": 1}}},
        ]
    ):
        by_priority[str(row["_id"])] = int(row["count"])

    return {
        "tenant_id": tid,
        "open_incidents": open_incidents,
        "open_changes": open_changes,
        "open_problems": open_problems,
        "by_status": by_status,
        "open_by_priority": by_priority,
        "pending_approvals": 0,  # Approvals product still out of scope
        "sla_breaches": 0,  # SLA engine still out of scope
        "notes": (
            "ITSM dashboard: incident / change / problem open counts. "
            "Approvals and SLA engines are not enabled yet."
        ),
    }
