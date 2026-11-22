"""Monitoring retention sweeper — count ceilings + wall-clock days (L9).

Soft retention mirrors plan limits (``metric_samples_retained``,
``log_events_retained``, ``max_diagnostic_runs``) plus entitlement-gated
``monitor_retention_days_*`` wall-clock deletes for the tenant's selected
tier (``hot`` | ``extended`` | ``siem``). Cold archive is a separate admin hook.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING

from ...config import Settings, get_settings
from ...services import entitlements as entitlements_service
from ...tenancy import require_tenant_id, tenant_filter
from . import cold_storage as cold_storage_service
from . import diagnostics as diagnostics_service
from . import live_gates as live_gates_service
from . import logs as logs_service
from . import targets as targets_service
from .cold_storage import ColdStorageError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sweep_tenant_retention(*, tenant_id: str) -> dict[str, Any]:
    """Trim over-age and over-limit time-series / history rows for one tenant."""
    tid = require_tenant_id(tenant_id)
    tier = live_gates_service.tenant_live_settings(tid)["monitor_retention_tier"]
    days = entitlements_service.effective_monitor_retention_days(tid)

    metric_age = targets_service.enforce_metric_samples_age_retention(
        tenant_id=tid, retention_days=days
    )
    metric_count = targets_service.enforce_metric_samples_retention(tenant_id=tid)
    log_age = logs_service.enforce_log_events_age_retention(
        tenant_id=tid, retention_days=days
    )
    log_count = logs_service.enforce_log_events_retention(tenant_id=tid)
    diag_trimmed = diagnostics_service.enforce_diagnostics_retention(tenant_id=tid)
    cold = cold_storage_service.cold_storage_status()
    return {
        "tenant_id": tid,
        "retention_tier": tier,
        "retention_days": days,
        "metric_samples_trimmed": metric_age + metric_count,
        "metric_samples_trimmed_by_age": metric_age,
        "metric_samples_trimmed_by_count": metric_count,
        "log_events_trimmed": log_age + log_count,
        "log_events_trimmed_by_age": log_age,
        "log_events_trimmed_by_count": log_count,
        "diagnostics_trimmed": diag_trimmed,
        "cold_storage": {
            "configured": bool(cold.get("configured")),
            "scheme": cold.get("scheme"),
        },
        "live_probes": False,
        "execution_mode": "SIMULATED",
    }


def run_cold_archive(
    *,
    tenant_id: str,
    older_than_days: int | None = None,
    limit: int = 5000,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Export aged log events to cold storage (file:// first; empty URI = no-op).

    Does **not** delete from Mongo — the retention sweeper still owns deletes.
    """
    tid = require_tenant_id(tenant_id)
    cfg = settings or get_settings()
    tier = live_gates_service.tenant_live_settings(tid)["monitor_retention_tier"]
    days = older_than_days
    if days is None:
        # Default: archive batches older than hot entitlement (or 7 when unlimited).
        hot = entitlements_service.monitor_retention_days_hot_limit(tid)
        days = int(hot) if hot is not None and int(hot) > 0 else 7
    days = max(1, int(days))
    lim = min(max(1, int(limit or 5000)), 50_000)
    cutoff = _now() - timedelta(days=days)

    # Fast path: empty URI → explicit no-op without scanning Mongo.
    uri = (cfg.monitor_cold_storage_uri or "").strip()
    if not uri:
        result = cold_storage_service.archive_log_events(
            tenant_id=tid, events=[], tier=tier, settings=cfg
        )
        return {
            **result,
            "retention_tier": tier,
            "older_than_days": days,
            "cutoff": cutoff.isoformat(),
            "candidates": 0,
        }

    from ...db import require_monitor_database

    coll = require_monitor_database()["log_events"]
    filt = {
        **tenant_filter(tid),
        "observed_at": {"$lt": cutoff},
    }
    events = list(
        coll.find(filt)
        .sort([("observed_at", ASCENDING), ("event_id", ASCENDING)])
        .limit(lim)
    )
    try:
        result = cold_storage_service.archive_log_events(
            tenant_id=tid, events=events, tier=tier, settings=cfg
        )
    except ColdStorageError as exc:
        return {
            "ok": False,
            "archived": False,
            "reason": exc.message,
            "tenant_id": tid,
            "retention_tier": tier,
            "older_than_days": days,
            "cutoff": cutoff.isoformat(),
            "candidates": len(events),
            "status": "error",
        }
    return {
        **result,
        "retention_tier": tier,
        "older_than_days": days,
        "cutoff": cutoff.isoformat(),
        "candidates": len(events),
    }
