"""Monitoring dashboard aggregates — monitor DB only (SIMULATED).

Counts targets, open alerts, log/file volume from ``svrmon-monitor``.
Never joins CMDB or ITSM MongoDB.
"""

from __future__ import annotations

from typing import Any

from ...serialization import serialize_document
from ...tenancy import require_tenant_id, tenant_filter
from .indexes import (
    ALERT_INSTANCES_COLLECTION,
    FILE_EVENTS_COLLECTION,
    LOG_EVENTS_COLLECTION,
    MONITOR_TARGETS_COLLECTION,
    ensure_monitor_indexes,
)
from .meta import BANNER, DATA_SOURCE, EXECUTION_MODE

OPEN_ALERT_STATUSES: tuple[str, ...] = ("firing", "acked")
RECENT_LIMIT = 8


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


def _recent(
    coll,
    match: dict[str, Any],
    *,
    sort_field: str,
    projection: dict[str, int],
    limit: int = RECENT_LIMIT,
) -> list[dict[str, Any]]:
    cursor = (
        coll.find(match, projection)
        .sort([(sort_field, -1)])
        .limit(limit)
    )
    return [serialize_document(doc) for doc in cursor]


def summary(*, tenant_id: str, settings: Any | None = None) -> dict[str, Any]:
    """Tenant-scoped Monitoring Dashboard KPIs from monitor collections."""
    from ...config import get_settings
    from ...db import require_monitor_database

    tid = require_tenant_id(tenant_id)
    ensure_monitor_indexes()
    db = require_monitor_database()
    base = tenant_filter(tid)
    cfg = settings or get_settings()

    targets = db[MONITOR_TARGETS_COLLECTION]
    alerts = db[ALERT_INSTANCES_COLLECTION]
    logs = db[LOG_EVENTS_COLLECTION]
    files = db[FILE_EVENTS_COLLECTION]

    targets_total = int(targets.count_documents(base))
    targets_by_status = _group_counts(targets, base, "status")
    targets_by_domain = _group_counts(targets, base, "domain")

    open_match = {**base, "status": {"$in": list(OPEN_ALERT_STATUSES)}}
    open_alerts = int(alerts.count_documents(open_match))
    alerts_by_status = _group_counts(alerts, base, "status")
    alerts_by_severity = _group_counts(alerts, open_match, "severity")

    log_events_total = int(logs.count_documents(base))
    file_events_total = int(files.count_documents(base))

    recent_open_alerts = _recent(
        alerts,
        open_match,
        sort_field="fired_at",
        projection={
            "_id": 0,
            "alert_id": 1,
            "rule_name": 1,
            "rule_id": 1,
            "status": 1,
            "severity": 1,
            "summary": 1,
            "component_id": 1,
            "fired_at": 1,
        },
    )
    recent_log_events = _recent(
        logs,
        base,
        sort_field="observed_at",
        projection={
            "_id": 0,
            "event_id": 1,
            "stream_id": 1,
            "component_id": 1,
            "severity": 1,
            "message": 1,
            "observed_at": 1,
        },
    )
    recent_file_events = _recent(
        files,
        base,
        sort_field="changed_at",
        projection={
            "_id": 0,
            "event_id": 1,
            "watch_id": 1,
            "path": 1,
            "version": 1,
            "changed_at": 1,
            "changed_by": 1,
            "component_id": 1,
        },
    )

    return {
        "module": "monitoring",
        "execution_mode": EXECUTION_MODE,
        "data_source": DATA_SOURCE,
        "demo_only": True,
        "live_probes": False,
        "banner": BANNER,
        "monitor_database": cfg.monitor_database_name,
        "tenant_id": tid,
        "targets_total": targets_total,
        "targets_by_status": targets_by_status,
        "targets_by_domain": targets_by_domain,
        "open_alerts": open_alerts,
        "alerts_by_status": alerts_by_status,
        "alerts_by_severity": alerts_by_severity,
        "log_events_total": log_events_total,
        "file_events_total": file_events_total,
        "recent_open_alerts": recent_open_alerts,
        "recent_log_events": recent_log_events,
        "recent_file_events": recent_file_events,
    }
