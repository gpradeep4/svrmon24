"""ITSM job tick — SLA sweeper, delivery retries, report-schedule placeholder.

Tenant-scoped scans with a process lease so multi-instance deploys do not
double-run the same job window. Safe to call with the runner disabled (manual
tick / tests).
"""

from __future__ import annotations

import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, ReturnDocument
from pymongo.collection import Collection

from ...config import Settings, get_settings
from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import require_tenant_id
from .indexes import JOB_LEASES, JOB_RUNS, SLA_TRACKING, ensure_itsm_indexes

logger = logging.getLogger(__name__)

JOB_SLA_SWEEPER = "sla_overdue_sweeper"
JOB_DELIVERY_RETRIES = "notification_delivery_retries"
JOB_REPORT_SCHEDULES = "report_schedules"
ALL_JOBS: tuple[str, ...] = (
    JOB_SLA_SWEEPER,
    JOB_DELIVERY_RETRIES,
    JOB_REPORT_SCHEDULES,
)


class JobError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _leases() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[JOB_LEASES]


def _runs() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[JOB_RUNS]


def _holder_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


def try_acquire_lease(
    job_name: str,
    *,
    lease_seconds: int,
    holder: str | None = None,
) -> dict[str, Any] | None:
    """Acquire or renew a short lease for ``job_name``. Returns None if held elsewhere."""
    if job_name not in ALL_JOBS:
        raise JobError(f"Unknown job '{job_name}'", status_code=422)
    now = _now()
    expires = now + timedelta(seconds=max(5, int(lease_seconds)))
    who = holder or _holder_id()
    coll = _leases()
    payload = {
        "job_name": job_name,
        "holder": who,
        "acquired_at": now,
        "expires_at": expires,
        "updated_at": now,
    }

    existing = coll.find_one({"job_name": job_name})
    if existing is None:
        try:
            coll.insert_one(payload)
            return serialize_document(coll.find_one({"job_name": job_name}))
        except Exception:  # noqa: BLE001 — unique race
            existing = coll.find_one({"job_name": job_name})
            if existing is None:
                return None

    exp = _ensure_aware(existing.get("expires_at"))
    held_by_us = existing.get("holder") == who
    expired = exp is None or exp <= now
    if not (held_by_us or expired):
        return None

    doc = coll.find_one_and_update(
        {
            "job_name": job_name,
            "$or": [
                {"holder": who},
                {"expires_at": {"$lte": now}},
                {"expires_at": None},
            ],
        },
        {"$set": payload},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None or doc.get("holder") != who:
        return None
    return serialize_document(doc)  # type: ignore[return-value]


def _ensure_aware(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return None


def sweep_sla_overdue(
    *,
    tenant_id: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Mark overdue running SLA clocks as breached (notifies via existing hook)."""
    from . import sla as sla_service

    now = _now()
    query: dict[str, Any] = {
        "status": "running",
        "due_at": {"$lt": now},
    }
    if tenant_id:
        query["tenant_id"] = require_tenant_id(tenant_id)

    coll = require_itsm_database()[SLA_TRACKING]
    cursor = coll.find(query).sort([("due_at", ASCENDING)]).limit(max(1, min(int(limit), 1000)))
    scanned = 0
    breached = 0
    notified_tenants: set[str] = set()
    for doc in cursor:
        scanned += 1
        tid = str(doc.get("tenant_id") or "")
        try:
            refreshed = sla_service._refresh_breach_doc(doc)
            if refreshed.get("status") == "breached":
                breached += 1
                if tid:
                    notified_tenants.add(tid)
        except Exception:  # noqa: BLE001
            logger.exception(
                "sla sweeper failed tracking_id=%s tenant=%s",
                doc.get("tracking_id"),
                tid,
            )
    return {
        "job": JOB_SLA_SWEEPER,
        "scanned": scanned,
        "breached": breached,
        "tenants": sorted(notified_tenants),
        "tenant_filter": tenant_id,
    }


def retry_notification_deliveries(
    *,
    tenant_id: str | None = None,
    limit: int = 100,
    max_attempts: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Retry failed outbound deliveries that are due for another attempt."""
    from . import notification_delivery as delivery_service

    cfg = settings or get_settings()
    max_att = int(max_attempts or cfg.itsm_delivery_max_attempts)
    now = _now()
    query: dict[str, Any] = {
        "status": "failed",
        "attempt": {"$lt": max_att},
        "$or": [
            {"next_retry_at": {"$lte": now}},
            {"next_retry_at": None},
        ],
    }
    if tenant_id:
        query["tenant_id"] = require_tenant_id(tenant_id)

    results = delivery_service.retry_due_deliveries(
        query=query,
        limit=limit,
        max_attempts=max_att,
    )
    return {
        "job": JOB_DELIVERY_RETRIES,
        **results,
        "tenant_filter": tenant_id,
        "max_attempts": max_att,
    }


def run_report_schedules_placeholder(
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Placeholder for N3 scheduled report delivery."""
    return {
        "job": JOB_REPORT_SCHEDULES,
        "ran": 0,
        "placeholder": True,
        "tenant_filter": tenant_id,
        "detail": "Report schedule runner lands in N3",
    }


def _record_run(job_name: str, result: dict[str, Any], *, holder: str) -> dict[str, Any]:
    now = _now()
    doc = {
        "run_id": f"JOBRUN-{uuid.uuid4().hex[:10].upper()}",
        "job_name": job_name,
        "holder": holder,
        "result": result,
        "created_at": now,
    }
    _runs().insert_one(doc)
    return serialize_document(doc)  # type: ignore[return-value]


def run_tick(
    *,
    tenant_id: str | None = None,
    jobs: list[str] | None = None,
    force: bool = False,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run selected jobs once. When ``force`` is False, skip jobs held by others."""
    cfg = settings or get_settings()
    selected = list(jobs) if jobs else list(ALL_JOBS)
    for name in selected:
        if name not in ALL_JOBS:
            raise JobError(f"Unknown job '{name}'", status_code=422)

    holder = _holder_id()
    lease_seconds = int(cfg.itsm_job_runner_lease_seconds)
    started = _now()
    outcomes: dict[str, Any] = {}
    skipped: list[str] = []

    for job_name in selected:
        if not force:
            lease = try_acquire_lease(
                job_name, lease_seconds=lease_seconds, holder=holder
            )
            if lease is None:
                skipped.append(job_name)
                outcomes[job_name] = {"skipped": True, "reason": "lease_held"}
                continue
        else:
            try_acquire_lease(job_name, lease_seconds=lease_seconds, holder=holder)

        try:
            if job_name == JOB_SLA_SWEEPER:
                result = sweep_sla_overdue(tenant_id=tenant_id)
            elif job_name == JOB_DELIVERY_RETRIES:
                result = retry_notification_deliveries(
                    tenant_id=tenant_id, settings=cfg
                )
            else:
                result = run_report_schedules_placeholder(tenant_id=tenant_id)
            _record_run(job_name, result, holder=holder)
            outcomes[job_name] = result
        except Exception as exc:  # noqa: BLE001 — tick must continue other jobs
            logger.exception("itsm job failed job=%s", job_name)
            outcomes[job_name] = {"error": str(exc)[:500]}

    return {
        "ok": True,
        "started_at": started.isoformat(),
        "finished_at": _now().isoformat(),
        "holder": holder,
        "tenant_filter": tenant_id,
        "forced": force,
        "skipped_jobs": skipped,
        "jobs": outcomes,
        "runner_enabled": bool(cfg.itsm_job_runner_enabled),
    }


def runner_status(*, settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    leases = []
    try:
        for doc in _leases().find({}).sort([("job_name", ASCENDING)]):
            leases.append(serialize_document(doc))
    except Exception:  # noqa: BLE001
        leases = []
    return {
        "enabled": bool(cfg.itsm_job_runner_enabled),
        "interval_seconds": int(cfg.itsm_job_runner_interval_seconds),
        "lease_seconds": int(cfg.itsm_job_runner_lease_seconds),
        "delivery_max_attempts": int(cfg.itsm_delivery_max_attempts),
        "jobs": list(ALL_JOBS),
        "leases": leases,
    }
