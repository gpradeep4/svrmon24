"""Best-effort workflow auto-triggers (on_create / on_status / schedule).

Never raises into ticket create/transition paths. Suppresses re-entry when the
workflow engine itself applies a status_change node.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from ...db import require_itsm_database
from ...tenancy import require_tenant_id
from . import workflow_engine as engine_service
from .indexes import WORKFLOWS, ensure_itsm_indexes

logger = logging.getLogger(__name__)

_suppress: ContextVar[bool] = ContextVar("itsm_wf_trigger_suppress", default=False)

OPEN_EXEC_STATUSES = ("running", "waiting_approval")
DEFAULT_SCHEDULE_MINUTES = 60
SCHEDULE_TICKET_CAP = 25


@contextmanager
def suppress_auto_triggers() -> Iterator[None]:
    token = _suppress.set(True)
    try:
        yield
    finally:
        _suppress.reset(token)


def auto_triggers_suppressed() -> bool:
    return bool(_suppress.get())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _wf_coll():
    ensure_itsm_indexes()
    return require_itsm_database()[WORKFLOWS]


def _normalize_trigger_config(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    statuses = raw.get("statuses")
    if isinstance(statuses, list):
        out["statuses"] = [
            str(s).strip() for s in statuses if str(s).strip()
        ]
    try:
        mins = int(raw.get("interval_minutes") or 0)
        if mins > 0:
            out["interval_minutes"] = min(mins, 60 * 24 * 30)
    except (TypeError, ValueError):
        pass
    return out


def has_open_execution(
    *,
    tenant_id: str,
    workflow_id: str,
    ticket_id: str,
) -> bool:
    tid = require_tenant_id(tenant_id)
    from .indexes import WORKFLOW_EXECUTIONS

    count = require_itsm_database()[WORKFLOW_EXECUTIONS].count_documents(
        {
            "tenant_id": tid,
            "workflow_id": workflow_id,
            "ticket_id": ticket_id,
            "status": {"$in": list(OPEN_EXEC_STATUSES)},
        }
    )
    return count > 0


def _matching_workflows(
    *,
    tenant_id: str,
    trigger: str,
    ticket_type: str,
) -> list[dict[str, Any]]:
    tid = require_tenant_id(tenant_id)
    query = {
        "tenant_id": tid,
        "active": True,
        "trigger": trigger,
        "applies_to": {"$in": [ticket_type, "generic"]},
    }
    return list(_wf_coll().find(query))


def _start_one(
    workflow: dict[str, Any],
    *,
    ticket_type: str,
    ticket_id: str,
    tenant_id: str,
    actor: dict[str, Any] | None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    workflow_id = str(workflow.get("workflow_id") or "")
    if not workflow_id:
        return None
    if has_open_execution(
        tenant_id=tenant_id, workflow_id=workflow_id, ticket_id=ticket_id
    ):
        logger.info(
            "workflow auto-trigger skip duplicate workflow=%s ticket=%s",
            workflow_id,
            ticket_id,
        )
        return None
    try:
        return engine_service.start_execution(
            workflow_id,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            tenant_id=tenant_id,
            actor=actor,
            context={
                "auto_trigger": True,
                "trigger": workflow.get("trigger"),
                **(context or {}),
            },
        )
    except Exception:  # noqa: BLE001 — best-effort
        logger.exception(
            "workflow auto-trigger failed workflow=%s ticket=%s/%s",
            workflow_id,
            ticket_type,
            ticket_id,
        )
        return None


def _automation_allowed(tenant_id: str) -> bool:
    """Fail-closed: platform ITSM_AUTOMATION_ENABLED + tenant opt-in."""
    from ...services import live_settings as live_settings_service

    return live_settings_service.itsm_automation_allowed(tenant_id=tenant_id)


def fire_on_create(
    *,
    ticket_type: str,
    ticket_id: str,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if auto_triggers_suppressed():
        return []
    if not _automation_allowed(tenant_id):
        return []
    started: list[dict[str, Any]] = []
    try:
        for wf in _matching_workflows(
            tenant_id=tenant_id, trigger="on_create", ticket_type=ticket_type
        ):
            doc = _start_one(
                wf,
                ticket_type=ticket_type,
                ticket_id=ticket_id,
                tenant_id=tenant_id,
                actor=actor,
                context={"event": "on_create"},
            )
            if doc:
                started.append(doc)
    except Exception:  # noqa: BLE001
        logger.exception("fire_on_create failed ticket=%s/%s", ticket_type, ticket_id)
    return started


def fire_on_status(
    *,
    ticket_type: str,
    ticket_id: str,
    from_status: str,
    to_status: str,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if auto_triggers_suppressed():
        return []
    if not _automation_allowed(tenant_id):
        return []
    started: list[dict[str, Any]] = []
    try:
        for wf in _matching_workflows(
            tenant_id=tenant_id, trigger="on_status", ticket_type=ticket_type
        ):
            cfg = _normalize_trigger_config(wf.get("trigger_config"))
            allowed = cfg.get("statuses") or []
            if allowed and to_status not in allowed:
                continue
            doc = _start_one(
                wf,
                ticket_type=ticket_type,
                ticket_id=ticket_id,
                tenant_id=tenant_id,
                actor=actor,
                context={
                    "event": "on_status",
                    "from_status": from_status,
                    "to_status": to_status,
                },
            )
            if doc:
                started.append(doc)
    except Exception:  # noqa: BLE001
        logger.exception(
            "fire_on_status failed ticket=%s/%s %s→%s",
            ticket_type,
            ticket_id,
            from_status,
            to_status,
        )
    return started


def _open_ticket_ids(ticket_type: str, *, tenant_id: str) -> list[str]:
    """Open tickets for schedule fan-out (excludes terminal statuses)."""
    tid = require_tenant_id(tenant_id)
    db = require_itsm_database()
    if ticket_type == "incident":
        coll, id_field = db["itsm_incidents"], "incident_id"
        closed = {"closed", "cancelled"}
    elif ticket_type == "change":
        coll, id_field = db["itsm_changes"], "change_id"
        closed = {"closed", "cancelled", "rejected"}
    elif ticket_type == "problem":
        coll, id_field = db["itsm_problems"], "problem_id"
        closed = {"closed", "cancelled"}
    else:
        return []
    cursor = (
        coll.find(
            {"tenant_id": tid, "status": {"$nin": list(closed)}},
            {id_field: 1},
        )
        .sort([("updated_at", -1)])
        .limit(SCHEDULE_TICKET_CAP)
    )
    return [str(doc[id_field]) for doc in cursor if doc.get(id_field)]


def _schedule_interval_minutes(wf: dict[str, Any]) -> int:
    cfg = _normalize_trigger_config(wf.get("trigger_config"))
    return int(cfg.get("interval_minutes") or DEFAULT_SCHEDULE_MINUTES)


def ensure_schedule_next_run(workflow_id: str, *, tenant_id: str) -> None:
    """When activating a schedule workflow, seed next_run_at if missing."""
    tid = require_tenant_id(tenant_id)
    doc = _wf_coll().find_one({"tenant_id": tid, "workflow_id": workflow_id})
    if not doc or doc.get("trigger") != "schedule":
        return
    if doc.get("next_run_at"):
        return
    _wf_coll().update_one(
        {"tenant_id": tid, "workflow_id": workflow_id},
        {"$set": {"next_run_at": _now(), "updated_at": _now()}},
    )


def run_due_workflow_schedules(
    *,
    tenant_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Job tick: start schedule-trigger workflows that are due (once per window)."""
    ensure_itsm_indexes()
    when = now or _now()
    started = 0
    skipped = 0
    workflows_due = 0
    errors = 0

    query: dict[str, Any] = {
        "active": True,
        "trigger": "schedule",
        "$or": [
            {"next_run_at": {"$lte": when}},
            {"next_run_at": None},
            {"next_run_at": {"$exists": False}},
        ],
    }
    if tenant_id:
        query["tenant_id"] = require_tenant_id(tenant_id)

    try:
        due = list(_wf_coll().find(query).limit(200))
    except Exception:  # noqa: BLE001
        logger.exception("workflow schedule scan failed")
        return {
            "job": "workflow_schedules",
            "workflows_due": 0,
            "executions_started": 0,
            "skipped": 0,
            "errors": 1,
            "tenant_filter": tenant_id,
        }

    for wf in due:
        workflows_due += 1
        tid = str(wf.get("tenant_id") or "")
        if tid and not _automation_allowed(tid):
            skipped += 1
            continue
        workflow_id = str(wf.get("workflow_id") or "")
        if not tid or not workflow_id:
            errors += 1
            continue
        applies = str(wf.get("applies_to") or "generic")
        types = (
            ["incident", "change", "problem"]
            if applies == "generic"
            else [applies]
        )
        try:
            for ticket_type in types:
                for ticket_id in _open_ticket_ids(ticket_type, tenant_id=tid):
                    if has_open_execution(
                        tenant_id=tid,
                        workflow_id=workflow_id,
                        ticket_id=ticket_id,
                    ):
                        skipped += 1
                        continue
                    doc = _start_one(
                        wf,
                        ticket_type=ticket_type,
                        ticket_id=ticket_id,
                        tenant_id=tid,
                        actor={
                            "user_id": "system",
                            "username": "workflow-schedule",
                        },
                        context={"event": "schedule"},
                    )
                    if doc:
                        started += 1
                    else:
                        skipped += 1

            interval = _schedule_interval_minutes(wf)
            next_at = when + timedelta(minutes=interval)
            _wf_coll().update_one(
                {"tenant_id": tid, "workflow_id": workflow_id},
                {"$set": {"next_run_at": next_at, "updated_at": when}},
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "workflow schedule tick failed workflow=%s tenant=%s",
                workflow_id,
                tid,
            )
            errors += 1

    return {
        "job": "workflow_schedules",
        "workflows_due": workflows_due,
        "executions_started": started,
        "skipped": skipped,
        "errors": errors,
        "tenant_filter": tenant_id,
    }
