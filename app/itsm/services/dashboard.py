"""ITSM dashboard and reports aggregates (ITSM DB only)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ...db import require_itsm_database
from ...tenancy import require_tenant_id, tenant_filter
from .indexes import (
    APPROVALS,
    CHANGES,
    INCIDENTS,
    KNOWLEDGE_ARTICLES,
    NOTIFICATIONS,
    PROBLEMS,
    SLA_TRACKING,
    WORKFLOW_EXECUTIONS,
    ensure_itsm_indexes,
)

OPEN_INC_STATUSES = ("new", "in_progress", "on_hold")
OPEN_CHG_STATUSES = (
    "draft",
    "submitted",
    "approved",
    "scheduled",
    "implementing",
    "review",
)
OPEN_PRB_STATUSES = ("new", "under_investigation", "known_error")
WF_IN_PROGRESS = ("running", "waiting_approval")
# Running/paused clocks due within this horizon count as at-risk (not yet breached).
SLA_AT_RISK_HOURS = 24
ALLOWED_WINDOWS = frozenset({7, 30})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _group_counts(coll, match: dict[str, Any], field: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in coll.aggregate(
        [
            {"$match": match},
            {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
        ]
    ):
        key = row["_id"]
        if key is None:
            continue
        out[str(key)] = int(row["count"])
    return out


def _refresh_overdue_breaches(sla_coll, base: dict[str, Any], now: datetime) -> None:
    """Best-effort: flip overdue running clocks to breached before counting."""
    sla_coll.update_many(
        {
            **base,
            "status": "running",
            "due_at": {"$lt": now},
        },
        {"$set": {"status": "breached", "breached_at": now, "updated_at": now}},
    )


def _window_start(window_days: int | None) -> datetime | None:
    if window_days is None:
        return None
    days = int(window_days)
    if days not in ALLOWED_WINDOWS:
        raise ValueError(f"window_days must be one of {sorted(ALLOWED_WINDOWS)}")
    return _now() - timedelta(days=days)


def summary(
    *,
    tenant_id: str,
    window_days: int | None = None,
) -> dict[str, Any]:
    """Tenant-scoped ITSM KPIs and optional time-window created/resolved counts."""
    tid = require_tenant_id(tenant_id)
    ensure_itsm_indexes()
    itsm = require_itsm_database()
    base = tenant_filter(tid)
    now = _now()
    start = _window_start(window_days)

    inc = itsm[INCIDENTS]
    chg = itsm[CHANGES]
    prb = itsm[PROBLEMS]
    apr = itsm[APPROVALS]
    sla = itsm[SLA_TRACKING]
    wx = itsm[WORKFLOW_EXECUTIONS]
    kb = itsm[KNOWLEDGE_ARTICLES]
    ntf = itsm[NOTIFICATIONS]

    _refresh_overdue_breaches(sla, base, now)

    open_incidents = inc.count_documents(
        {**base, "status": {"$in": list(OPEN_INC_STATUSES)}}
    )
    open_changes = chg.count_documents(
        {**base, "status": {"$in": list(OPEN_CHG_STATUSES)}}
    )
    open_problems = prb.count_documents(
        {**base, "status": {"$in": list(OPEN_PRB_STATUSES)}}
    )

    incidents_by_status = _group_counts(inc, base, "status")
    changes_by_status = _group_counts(chg, base, "status")
    problems_by_status = _group_counts(prb, base, "status")

    open_by_priority = _group_counts(
        inc,
        {**base, "status": {"$in": list(OPEN_INC_STATUSES)}},
        "priority",
    )
    changes_by_priority = _group_counts(
        chg,
        {**base, "status": {"$in": list(OPEN_CHG_STATUSES)}},
        "priority",
    )
    problems_by_priority = _group_counts(
        prb,
        {**base, "status": {"$in": list(OPEN_PRB_STATUSES)}},
        "priority",
    )

    pending_approvals = apr.count_documents({**base, "status": "pending"})
    sla_breaches = sla.count_documents({**base, "status": "breached"})
    at_risk_deadline = now + timedelta(hours=SLA_AT_RISK_HOURS)
    sla_at_risk = sla.count_documents(
        {
            **base,
            "status": {"$in": ["running", "paused"]},
            "due_at": {"$gt": now, "$lte": at_risk_deadline},
        }
    )
    workflows_in_progress = wx.count_documents(
        {**base, "status": {"$in": list(WF_IN_PROGRESS)}}
    )
    knowledge_published = kb.count_documents({**base, "status": "published"})
    notifications_unread = ntf.count_documents({**base, "status": "unread"})

    created_in_window = {"incidents": 0, "changes": 0, "problems": 0}
    resolved_in_window = {"incidents": 0, "changes": 0, "problems": 0}
    if start is not None:
        created_clause = {"created_at": {"$gte": start}}
        created_in_window = {
            "incidents": inc.count_documents({**base, **created_clause}),
            "changes": chg.count_documents({**base, **created_clause}),
            "problems": prb.count_documents({**base, **created_clause}),
        }
        resolved_in_window = {
            "incidents": inc.count_documents(
                {
                    **base,
                    "status": {"$in": ["resolved", "closed"]},
                    "$or": [
                        {"resolved_at": {"$gte": start}},
                        {"closed_at": {"$gte": start}},
                    ],
                }
            ),
            "changes": chg.count_documents(
                {
                    **base,
                    "status": "closed",
                    "updated_at": {"$gte": start},
                }
            ),
            "problems": prb.count_documents(
                {
                    **base,
                    "status": {"$in": ["resolved", "closed"]},
                    "updated_at": {"$gte": start},
                }
            ),
        }

    return {
        "tenant_id": tid,
        "window_days": int(window_days) if window_days is not None else None,
        "window_start": start.isoformat() if start is not None else None,
        "generated_at": now.isoformat(),
        "open_incidents": open_incidents,
        "open_changes": open_changes,
        "open_problems": open_problems,
        "by_status": incidents_by_status,
        "incidents_by_status": incidents_by_status,
        "changes_by_status": changes_by_status,
        "problems_by_status": problems_by_status,
        "open_by_priority": open_by_priority,
        "incidents_open_by_priority": open_by_priority,
        "changes_open_by_priority": changes_by_priority,
        "problems_open_by_priority": problems_by_priority,
        "pending_approvals": pending_approvals,
        "sla_breaches": sla_breaches,
        "sla_at_risk": sla_at_risk,
        "workflows_in_progress": workflows_in_progress,
        "knowledge_published": knowledge_published,
        "notifications_unread": notifications_unread,
        "created_in_window": created_in_window,
        "resolved_in_window": resolved_in_window,
        "notes": (
            "ITSM dashboard: open tickets by status/priority, SLA breach/at-risk, "
            "pending approvals, workflows in progress, published knowledge, "
            "and unread notifications. Optional window_days=7|30 scopes created/resolved."
        ),
    }


def reports(
    *,
    tenant_id: str,
    window_days: int = 30,
) -> dict[str, Any]:
    """Reports view: summary plus simple volume series for the selected window."""
    if window_days not in ALLOWED_WINDOWS:
        raise ValueError(f"window_days must be one of {sorted(ALLOWED_WINDOWS)}")
    base_summary = summary(tenant_id=tenant_id, window_days=window_days)
    tid = base_summary["tenant_id"]
    itsm = require_itsm_database()
    base = tenant_filter(tid)
    start = datetime.fromisoformat(base_summary["window_start"])

    series = _daily_created_series(
        itsm[INCIDENTS],
        itsm[CHANGES],
        itsm[PROBLEMS],
        base=base,
        start=start,
        days=window_days,
    )
    return {
        **base_summary,
        "series_daily_created": series,
        "notes": (
            "ITSM reports: dashboard KPIs plus daily created ticket volumes "
            f"for the last {window_days} days."
        ),
    }


def _daily_created_series(
    inc,
    chg,
    prb,
    *,
    base: dict[str, Any],
    start: datetime,
    days: int,
) -> list[dict[str, Any]]:
    """Build a dense day-bucket series of created ticket counts."""
    buckets: dict[str, dict[str, int]] = {}
    day0 = start.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    for i in range(days + 1):
        key = (day0 + timedelta(days=i)).date().isoformat()
        buckets[key] = {"incidents": 0, "changes": 0, "problems": 0}

    def _fill(coll, field: str) -> None:
        for row in coll.aggregate(
            [
                {"$match": {**base, "created_at": {"$gte": start}}},
                {
                    "$group": {
                        "_id": {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": "$created_at",
                            }
                        },
                        "count": {"$sum": 1},
                    }
                },
            ]
        ):
            key = str(row["_id"])
            if key in buckets:
                buckets[key][field] = int(row["count"])

    _fill(inc, "incidents")
    _fill(chg, "changes")
    _fill(prb, "problems")

    return [
        {
            "date": key,
            "incidents": vals["incidents"],
            "changes": vals["changes"],
            "problems": vals["problems"],
            "total": vals["incidents"] + vals["changes"] + vals["problems"],
        }
        for key, vals in sorted(buckets.items())
    ]
