"""Scheduled ITSM report delivery (email via N1 channels; run via N2 job tick)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from ..models.reports import ReportScheduleCreate, ReportScheduleUpdate
from . import notification_channels as channel_settings_service
from . import reports as reports_service
from .indexes import REPORT_SCHEDULE_RUNS, REPORT_SCHEDULES, ensure_itsm_indexes
from .notification_providers import DeliveryResult, get_provider
from .reports import ReportError

logger = logging.getLogger(__name__)


class ScheduleError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _schedules() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[REPORT_SCHEDULES]


def _runs() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[REPORT_SCHEDULE_RUNS]


def _new_schedule_id() -> str:
    return f"RSCH-{uuid.uuid4().hex[:10].upper()}"


def _new_run_id() -> str:
    return f"RSRUN-{uuid.uuid4().hex[:10].upper()}"


def _actor_fields(actor: dict[str, Any] | None) -> dict[str, str | None]:
    actor = actor or {}
    return {
        "user_id": actor.get("user_id") or actor.get("username"),
        "username": actor.get("username") or actor.get("user_id"),
    }


def _next_run(from_time: datetime, interval_minutes: int) -> datetime:
    mins = max(5, int(interval_minutes))
    return from_time + timedelta(minutes=mins)


def get_schedule(schedule_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _schedules().find_one({"tenant_id": tid, "schedule_id": schedule_id})
    return serialize_document(doc)


def list_schedules(
    *,
    tenant_id: str,
    active: bool | None = None,
    report_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    clauses: list[dict[str, Any]] = []
    if active is not None:
        clauses.append({"active": bool(active)})
    if report_id:
        clauses.append({"report_id": str(report_id).strip()})
    query: dict[str, Any] = {"$and": clauses} if clauses else {}
    scoped = merge_tenant_filter(query, tid)
    coll = _schedules()
    total = coll.count_documents(scoped)
    cursor = (
        coll.find(scoped)
        .sort([("updated_at", DESCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "tenant_id": tid,
    }


def create_schedule(
    payload: ReportScheduleCreate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    report = reports_service.get_definition(payload.report_id, tenant_id=tid)
    if report is None:
        raise ScheduleError(
            f"Report '{payload.report_id}' not found", status_code=404
        )
    now = _now()
    who = _actor_fields(actor)
    doc: dict[str, Any] = {
        "schedule_id": _new_schedule_id(),
        "report_id": payload.report_id,
        "report_name": report.get("name"),
        "name": payload.name or f"Schedule for {report.get('name')}",
        "interval_minutes": int(payload.interval_minutes),
        "timezone": payload.timezone or "UTC",
        "recipients": list(payload.recipients),
        "channels": list(payload.channels),
        "format": payload.format,
        "active": bool(payload.active),
        "next_run_at": now if payload.active else None,
        "last_run_at": None,
        "last_status": None,
        "last_error": None,
        "created_at": now,
        "updated_at": now,
        "created_by_user_id": who["user_id"],
        "created_by_username": who["username"],
        "updated_by_user_id": who["user_id"],
        "updated_by_username": who["username"],
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _schedules().insert_one(doc)
    return serialize_document(doc)  # type: ignore[return-value]


def update_schedule(
    schedule_id: str,
    payload: ReportScheduleUpdate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _schedules().find_one({"tenant_id": tid, "schedule_id": schedule_id})
    if existing is None:
        raise ScheduleError(f"Schedule '{schedule_id}' not found", status_code=404)
    data = payload.model_dump(exclude_unset=True)
    who = _actor_fields(actor)
    updates: dict[str, Any] = {
        "updated_at": _now(),
        "updated_by_user_id": who["user_id"],
        "updated_by_username": who["username"],
    }
    for key in (
        "name",
        "interval_minutes",
        "timezone",
        "recipients",
        "channels",
        "format",
        "active",
    ):
        if key in data:
            updates[key] = data[key]

    # If re-enabled with no next_run_at, schedule immediately.
    becoming_active = updates.get("active", existing.get("active"))
    if becoming_active and (
        "active" in data or "interval_minutes" in data or existing.get("next_run_at") is None
    ):
        if updates.get("active", existing.get("active")):
            if existing.get("next_run_at") is None or data.get("active") is True:
                updates["next_run_at"] = _now()
    if data.get("active") is False:
        updates["next_run_at"] = None

    doc = _schedules().find_one_and_update(
        {"tenant_id": tid, "schedule_id": schedule_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise ScheduleError(f"Schedule '{schedule_id}' not found", status_code=404)
    return serialize_document(doc)  # type: ignore[return-value]


def delete_schedule(schedule_id: str, *, tenant_id: str) -> None:
    tid = require_tenant_id(tenant_id)
    result = _schedules().delete_one({"tenant_id": tid, "schedule_id": schedule_id})
    if result.deleted_count == 0:
        raise ScheduleError(f"Schedule '{schedule_id}' not found", status_code=404)


def list_schedule_runs(
    *,
    tenant_id: str,
    schedule_id: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    query: dict[str, Any] = {"tenant_id": tid}
    if schedule_id:
        query["schedule_id"] = schedule_id
    coll = _runs()
    total = coll.count_documents(query)
    cursor = (
        coll.find(query)
        .sort([("created_at", DESCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "tenant_id": tid,
    }


def _send_report_email(
    *,
    tenant_id: str,
    to_addr: str,
    subject: str,
    body: str,
    filename: str,
    content: bytes,
    fmt: str,
) -> DeliveryResult:
    settings = channel_settings_service.get_channel_settings(
        tenant_id=tenant_id, channel="email"
    )
    if not settings.get("enabled"):
        return DeliveryResult(
            status="skipped",
            provider="smtp",
            recipient_address=to_addr,
            error="channel_disabled",
        )
    provider = get_provider("email")
    if provider is None:
        return DeliveryResult(
            status="skipped",
            provider="none",
            recipient_address=to_addr,
            error="provider_missing",
        )
    subtype = (
        "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if fmt == "xlsx"
        else "csv"
    )
    return provider.deliver(  # type: ignore[call-arg]
        recipient_address=to_addr,
        subject=subject,
        body=body,
        channel_config=settings,
        attachments=[
            {
                "filename": filename,
                "content": content,
                "maintype": "application" if fmt == "xlsx" else "text",
                "subtype": subtype if fmt == "xlsx" else "csv",
            }
        ],
    )


def execute_schedule(
    schedule: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Run one schedule: export report and email recipients. Updates schedule + run log."""
    tid = require_tenant_id(str(schedule.get("tenant_id") or ""))
    schedule_id = str(schedule.get("schedule_id") or "")
    report_id = str(schedule.get("report_id") or "")
    now = _now()
    fmt = str(schedule.get("format") or "csv").lower()
    recipients = list(schedule.get("recipients") or [])

    run_doc: dict[str, Any] = {
        "run_id": _new_run_id(),
        "schedule_id": schedule_id,
        "report_id": report_id,
        "status": "running",
        "forced": force,
        "recipients": recipients,
        "format": fmt,
        "delivery_results": [],
        "error": None,
        "created_at": now,
        "finished_at": None,
    }
    stamp_tenant_id(run_doc, tenant_id=tid)

    try:
        if not schedule.get("active") and not force:
            raise ScheduleError("Schedule is inactive", status_code=400)
        result = reports_service.run_definition(report_id, tenant_id=tid)
        body, filename, count = reports_service.render_run_export(result, fmt=fmt)
        subject = (
            f"[ITSM] Scheduled report: {schedule.get('name') or result.get('name') or report_id}"
        )
        text = (
            f"Scheduled ITSM report '{result.get('name') or report_id}' "
            f"({count} row(s), format {fmt}).\n"
            f"Generated at {result.get('generated_at') or now.isoformat()}."
        )
        deliveries: list[dict[str, Any]] = []
        any_sent = False
        last_error: str | None = None
        for addr in recipients:
            dr = _send_report_email(
                tenant_id=tid,
                to_addr=addr,
                subject=subject,
                body=text,
                filename=filename,
                content=body,
                fmt=fmt,
            )
            deliveries.append(
                {
                    "recipient": addr,
                    "status": dr.status,
                    "error": dr.error,
                    "provider": dr.provider,
                }
            )
            if dr.status == "sent":
                any_sent = True
            elif dr.error:
                last_error = dr.error
        status = "sent" if any_sent else ("failed" if last_error else "skipped")
        run_doc["status"] = status
        run_doc["delivery_results"] = deliveries
        run_doc["error"] = None if any_sent else last_error
        run_doc["export_count"] = count
        run_doc["filename"] = filename
    except (ScheduleError, ReportError) as exc:
        run_doc["status"] = "failed"
        run_doc["error"] = getattr(exc, "message", str(exc))[:500]
    except Exception as exc:  # noqa: BLE001
        logger.exception("report schedule execute failed schedule=%s", schedule_id)
        run_doc["status"] = "failed"
        run_doc["error"] = str(exc)[:500]

    run_doc["finished_at"] = _now()
    _runs().insert_one(run_doc)

    interval = int(schedule.get("interval_minutes") or 1440)
    schedule_updates: dict[str, Any] = {
        "last_run_at": now,
        "last_status": run_doc["status"],
        "last_error": run_doc.get("error"),
        "updated_at": _now(),
    }
    if schedule.get("active"):
        schedule_updates["next_run_at"] = _next_run(now, interval)
    else:
        schedule_updates["next_run_at"] = None

    _schedules().update_one(
        {"tenant_id": tid, "schedule_id": schedule_id},
        {"$set": schedule_updates},
    )
    return serialize_document(run_doc)  # type: ignore[return-value]


def run_due_schedules(
    *,
    tenant_id: str | None = None,
    limit: int = 50,
    force_schedule_id: str | None = None,
) -> dict[str, Any]:
    """Execute due (or forced) active schedules. Used by the N2 job tick."""
    now = _now()
    coll = _schedules()
    if force_schedule_id:
        query: dict[str, Any] = {"schedule_id": force_schedule_id}
        if tenant_id:
            query["tenant_id"] = require_tenant_id(tenant_id)
        docs = list(coll.find(query).limit(1))
        forced = True
    else:
        query = {
            "active": True,
            "next_run_at": {"$lte": now},
        }
        if tenant_id:
            query["tenant_id"] = require_tenant_id(tenant_id)
        docs = list(
            coll.find(query)
            .sort([("next_run_at", ASCENDING)])
            .limit(max(1, min(int(limit), 200)))
        )
        forced = False

    ran = 0
    sent = 0
    failed = 0
    skipped = 0
    run_ids: list[str] = []
    for doc in docs:
        # Claim due row to reduce double-send races.
        if not forced:
            claimed = coll.find_one_and_update(
                {
                    "tenant_id": doc.get("tenant_id"),
                    "schedule_id": doc.get("schedule_id"),
                    "active": True,
                    "next_run_at": {"$lte": now},
                },
                {
                    "$set": {
                        "next_run_at": _next_run(
                            now, int(doc.get("interval_minutes") or 1440)
                        ),
                        "updated_at": _now(),
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
            if claimed is None:
                skipped += 1
                continue
            target = claimed
        else:
            target = doc
        result = execute_schedule(target, force=forced)
        ran += 1
        run_ids.append(str(result.get("run_id")))
        if result.get("status") == "sent":
            sent += 1
        elif result.get("status") == "failed":
            failed += 1
        else:
            skipped += 1

    return {
        "job": "report_schedules",
        "ran": ran,
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "run_ids": run_ids,
        "tenant_filter": tenant_id,
        "placeholder": False,
    }
