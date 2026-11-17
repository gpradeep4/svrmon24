"""Light ITSM dashboard aggregates (ITSM DB)."""

from __future__ import annotations

from typing import Any

from ...db import require_itsm_database
from ...tenancy import require_tenant_id, tenant_filter
from .indexes import INCIDENTS, ensure_itsm_indexes


def summary(*, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    ensure_itsm_indexes()
    coll = require_itsm_database()[INCIDENTS]
    base = tenant_filter(tid)

    open_statuses = ["new", "in_progress", "on_hold"]
    open_count = coll.count_documents({**base, "status": {"$in": open_statuses}})
    by_status: dict[str, int] = {}
    for row in coll.aggregate(
        [
            {"$match": base},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
    ):
        by_status[str(row["_id"])] = int(row["count"])

    by_priority: dict[str, int] = {}
    for row in coll.aggregate(
        [
            {"$match": {**base, "status": {"$in": open_statuses}}},
            {"$group": {"_id": "$priority", "count": {"$sum": 1}}},
        ]
    ):
        by_priority[str(row["_id"])] = int(row["count"])

    return {
        "tenant_id": tid,
        "open_incidents": open_count,
        "by_status": by_status,
        "open_by_priority": by_priority,
        "pending_approvals": 0,  # stub — Approvals out of scope for this slice
        "sla_breaches": 0,  # stub — SLA engine out of scope
        "notes": (
            "ITSM dashboard stub: incident aggregates only. "
            "Approvals / SLA / Change / Problem modules are not enabled yet."
        ),
    }
