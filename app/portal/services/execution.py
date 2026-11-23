"""Service Portal execution runs + CMDB sync (SP6) + LIVE adapters (SP10).

SIMULATED remains default. LIVE / live DRY_RUN require platform + tenant gates
(fail-closed). ``simulate_tick`` advances SIMULATED runs; ``advance_run`` also
drives LIVE once enqueued.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument
from pymongo.collection import Collection

from ...cmdb.models.components import ComponentCreate, ComponentUpdate
from ...cmdb.services import components as components_service
from ...cmdb.services.components import ComponentError
from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from .indexes import EXECUTION_RUNS, REQUESTS, ensure_portal_indexes
from . import notifications as portal_notifications
from .requests import RequestError, get_request

_TERMINAL_RUN = frozenset({"succeeded", "failed", "cancelled"})


class ExecutionError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _runs() -> Collection:
    ensure_portal_indexes()
    return require_itsm_database()[EXECUTION_RUNS]


def _requests() -> Collection:
    ensure_portal_indexes()
    return require_itsm_database()[REQUESTS]


def _new_run_id() -> str:
    return f"SPRUN-{uuid.uuid4().hex[:12].upper()}"


def _actor_name(actor: dict[str, Any] | None) -> str | None:
    actor = actor or {}
    return actor.get("user_id") or actor.get("username")


def enqueue_execution(
    request_id: str,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Create a queued ``sp_execution_runs`` row for an approved request."""
    tid = require_tenant_id(tenant_id)
    from ...services import entitlements as entitlements_service
    from ...services.entitlements import EntitlementError

    try:
        entitlements_service.assert_can_enqueue_sp_execution(tid)
    except EntitlementError as exc:
        raise ExecutionError(exc.message, status_code=exc.status_code) from exc
    req = get_request(tenant_id=tid, request_id=request_id)
    status = req.get("status")
    if status not in ("approved", "queued", "failed") and not force:
        raise ExecutionError(
            f"cannot enqueue execution for request status '{status}'",
            status_code=409,
        )

    # Avoid duplicate active runs unless force/requeue.
    existing = _runs().find_one(
        merge_tenant_filter(
            {
                "request_id": request_id,
                "status": {"$in": ["queued", "running"]},
            },
            tid,
        )
    )
    if existing and not force:
        return serialize_document(existing)  # type: ignore[return-value]

    mode = req.get("requested_execution_mode") or "SIMULATED"
    collect = str(req.get("collect_mode") or "agentless").lower()
    if mode == "LIVE":
        from . import live_gates as live_gates_service

        try:
            live_gates_service.assert_live_allowed(
                tenant_id=tid, capability="live_exec"
            )
            live_gates_service.assert_live_allowed(
                tenant_id=tid,
                capability="agent" if collect == "agent" else "agentless",
            )
        except Exception as exc:  # noqa: BLE001 — FastAPI HTTPException or other
            status = getattr(exc, "status_code", 403) or 403
            detail = getattr(exc, "detail", None) or str(exc)
            raise ExecutionError(str(detail), status_code=int(status)) from exc
        execution_mode = "LIVE"
    elif mode == "DRY_RUN":
        execution_mode = "DRY_RUN"
    else:
        execution_mode = "SIMULATED"

    now = _now()
    who = _actor_name(actor)
    doc: dict[str, Any] = {
        "run_id": _new_run_id(),
        "request_id": request_id,
        "change_id": req.get("change_id"),
        "item_id": req.get("item_id"),
        "item_key_snapshot": req.get("item_key_snapshot"),
        "action_key": req.get("action_key"),
        "adapter": (req.get("domain") or "other"),
        "execution_mode": execution_mode,
        "collect_mode": collect,
        "dry_run": execution_mode == "DRY_RUN",
        "status": "queued",
        "started_at": None,
        "finished_at": None,
        "result_summary": None,
        "result_detail": None,
        "provisioned_facts": None,
        "cmdb_sync_status": req.get("cmdb_sync_status") or "none",
        "component_id": req.get("component_id"),
        "error_code": None,
        "created_at": now,
        "updated_at": now,
        "created_by": who,
        "updated_by": who,
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _runs().insert_one(doc)

    _requests().update_one(
        merge_tenant_filter({"request_id": request_id}, tid),
        {
            "$set": {
                "status": "queued",
                "updated_at": now,
                "updated_by": who,
            }
        },
    )
    from . import audit as portal_audit

    portal_audit.record_portal_event(
        tenant_id=tid,
        action="portal.execution.enqueue",
        actor=actor,
        request_id=request_id,
        change_id=req.get("change_id"),
        resource_type="sp_execution_run",
        resource_id=doc["run_id"],
        details={
            "action_key": doc.get("action_key"),
            "collect_mode": doc.get("collect_mode"),
            "execution_mode": doc.get("execution_mode"),
        },
    )
    return serialize_document(doc)  # type: ignore[return-value]


def get_run(*, tenant_id: str, run_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    doc = _runs().find_one(merge_tenant_filter({"run_id": run_id}, tid))
    if not doc:
        raise ExecutionError("execution run not found", status_code=404)
    return serialize_document(doc)  # type: ignore[return-value]


def list_runs(
    *,
    tenant_id: str,
    status: str | None = None,
    request_id: str | None = None,
    domain: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    clauses: list[dict[str, Any]] = []
    if status:
        clauses.append({"status": status})
    if request_id:
        clauses.append({"request_id": request_id})
    if domain:
        clauses.append({"adapter": domain})
    base = {"$and": clauses} if clauses else None
    query = merge_tenant_filter(base, tid)
    coll = _runs()
    total = coll.count_documents(query)
    skip = max(0, (page - 1) * page_size)
    cursor = (
        coll.find(query)
        .sort([("created_at", -1)])
        .skip(skip)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "execution_mode_default": "SIMULATED",
    }


def _live_dry_run_allowed(*, tid: str, collect: str) -> bool:
    """True when DRY_RUN should use live adapters (gates open for collect mode)."""
    from . import live_gates as live_gates_service

    gates = live_gates_service.live_gates(tenant_id=tid)
    if not gates.get("live_exec"):
        return False
    if collect == "agent":
        return bool(gates.get("agent_enabled"))
    return bool(gates.get("agentless_enabled"))


def _simulate_handler(run: dict[str, Any], req: dict[str, Any]) -> dict[str, Any]:
    """Produce synthetic AGENT / AGENTLESS results (no sockets)."""
    collect = (run.get("collect_mode") or "agentless").lower()
    action = run.get("action_key") or "unknown"
    if str(action).startswith("vuln."):
        from . import vuln as vuln_service

        tid = str(req.get("tenant_id") or run.get("tenant_id") or "")
        out = vuln_service.dispatch_vuln_action(
            tenant_id=tid,
            req=req,
            run={**run, "execution_mode": run.get("execution_mode") or "SIMULATED"},
        )
        return {
            "result_summary": out["result_summary"],
            "result_detail": out["result_detail"],
            "provisioned_facts": out["provisioned_facts"],
        }
    values = req.get("form_values") or {}
    path = "agent" if collect == "agent" else "agentless"
    facts: dict[str, Any] = {
        "simulated": True,
        "path": path,
        "action_key": action,
        "echo_fields": {
            k: v for k, v in values.items() if not str(k).endswith("_secret")
        },
    }
    if "hostname" in values:
        facts["hostname"] = values.get("hostname")
    if "username" in values:
        facts["username"] = values.get("username")
    summary = (
        f"SIMULATED {path} run for {action} "
        f"({'dry-run plan' if run.get('dry_run') else 'synthetic mutate'})"
    )
    detail = {
        "steps": [
            {"step": "validate", "ok": True},
            {"step": f"dispatch_{path}", "ok": True, "mode": "SIMULATED"},
            {"step": "apply" if not run.get("dry_run") else "plan", "ok": True},
        ],
        "stdout": f"[simulated] completed {action}",
        "stderr": "",
    }
    return {
        "result_summary": summary,
        "result_detail": detail,
        "provisioned_facts": facts,
    }


def _apply_cmdb_sync(
    *,
    tid: str,
    req: dict[str, Any],
    run: dict[str, Any],
) -> dict[str, Any]:
    """Best-effort CMDB create/update after successful provision (OD-11)."""
    sync_mode = req.get("cmdb_sync") or "none"
    if sync_mode not in ("create", "update"):
        return {
            "cmdb_sync_status": "none",
            "component_id": req.get("component_id"),
            "cmdb_sync_error": None,
        }

    catalog_meta: dict[str, Any] = {}
    try:
        from . import catalog as catalog_service

        catalog_meta = catalog_service.get_catalog_item(
            tenant_id=tid, item_id=req["item_id"]
        )
    except Exception:  # noqa: BLE001
        catalog_meta = {}

    values = dict(req.get("form_values") or {})
    facts = dict(run.get("provisioned_facts") or {})
    field_map = dict(
        req.get("cmdb_field_map")
        or catalog_meta.get("cmdb_field_map")
        or {}
    )
    # Default map: form field → component attr when no explicit map.
    mapped: dict[str, Any] = {}
    for src, dest in field_map.items():
        if src in values:
            mapped[dest] = values[src]
    for key in ("hostname", "os_family", "os_version", "name", "environment"):
        if key in values and key not in mapped:
            mapped[key] = values[key]
    if "hostname" in facts and "hostname" not in mapped:
        mapped["hostname"] = facts["hostname"]

    ctype = (
        req.get("cmdb_component_type")
        or catalog_meta.get("cmdb_component_type")
        or "server"
    )
    name = (
        mapped.get("name")
        or mapped.get("hostname")
        or values.get("hostname")
        or values.get("title")
        or f"sp-{req.get('request_id')}"
    )
    environment = mapped.get("environment") or values.get("environment") or "lab"

    try:
        if sync_mode == "create":
            payload = ComponentCreate(
                component_type=ctype,  # type: ignore[arg-type]
                name=str(name)[:256],
                environment=str(environment)[:128],
                hostname=mapped.get("hostname"),
                os_family=mapped.get("os_family"),
                os_version=mapped.get("os_version"),
            )
            created = components_service.create_component(payload, tenant_id=tid)
            return {
                "cmdb_sync_status": "succeeded",
                "component_id": created.get("component_id"),
                "cmdb_sync_error": None,
            }
        # update
        component_id = req.get("component_id") or values.get("target_ci")
        if not component_id:
            return {
                "cmdb_sync_status": "failed",
                "component_id": None,
                "cmdb_sync_error": "no component_id for cmdb_sync=update",
            }
        patch = ComponentUpdate(
            name=str(name)[:256] if name else None,
            hostname=mapped.get("hostname"),
            os_family=mapped.get("os_family"),
            os_version=mapped.get("os_version"),
        )
        updated = components_service.update_component(
            str(component_id), patch, tenant_id=tid
        )
        return {
            "cmdb_sync_status": "succeeded",
            "component_id": updated.get("component_id") or component_id,
            "cmdb_sync_error": None,
        }
    except (ComponentError, Exception) as exc:  # noqa: BLE001
        msg = getattr(exc, "message", None) or str(exc)
        return {
            "cmdb_sync_status": "failed",
            "component_id": req.get("component_id"),
            "cmdb_sync_error": msg[:500],
        }


def _finish_run(
    run_id: str,
    *,
    tid: str,
    status: str,
    updates: dict[str, Any],
    actor: dict[str, Any] | None,
) -> dict[str, Any]:
    now = _now()
    updates = {
        **updates,
        "status": status,
        "finished_at": now,
        "updated_at": now,
        "updated_by": _actor_name(actor),
    }
    result = _runs().find_one_and_update(
        merge_tenant_filter({"run_id": run_id}, tid),
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise ExecutionError("execution run not found", status_code=404)
    return serialize_document(result)  # type: ignore[return-value]


def advance_run(
    run_id: str,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Advance one run: queued→running→succeeded (+ CMDB sync)."""
    tid = require_tenant_id(tenant_id)
    run = get_run(tenant_id=tid, run_id=run_id)
    status = run.get("status")
    if status in _TERMINAL_RUN:
        return run

    now = _now()
    who = _actor_name(actor)

    if status == "queued":
        result = _runs().find_one_and_update(
            merge_tenant_filter({"run_id": run_id, "status": "queued"}, tid),
            {
                "$set": {
                    "status": "running",
                    "started_at": now,
                    "updated_at": now,
                    "updated_by": who,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if not result:
            return get_run(tenant_id=tid, run_id=run_id)
        _requests().update_one(
            merge_tenant_filter({"request_id": result["request_id"]}, tid),
            {"$set": {"status": "running", "updated_at": now, "updated_by": who}},
        )
        return serialize_document(result)  # type: ignore[return-value]

    if status != "running":
        raise ExecutionError(f"cannot advance run in status '{status}'", status_code=409)

    try:
        req = get_request(tenant_id=tid, request_id=run["request_id"])
    except RequestError as exc:
        return _finish_run(
            run_id,
            tid=tid,
            status="failed",
            updates={
                "error_code": "request_missing",
                "result_summary": exc.message,
            },
            actor=actor,
        )

    exec_mode = str(run.get("execution_mode") or "SIMULATED").upper()
    use_live = exec_mode == "LIVE" or (
        exec_mode == "DRY_RUN"
        and _live_dry_run_allowed(tid=tid, collect=str(run.get("collect_mode") or "agentless"))
    )
    try:
        if use_live:
            from .adapters import AdapterError, execute_live

            live = execute_live(run=run, req=req, tenant_id=tid)
            handler_out = {
                "result_summary": live.result_summary,
                "result_detail": live.result_detail,
                "provisioned_facts": live.provisioned_facts,
            }
        else:
            handler_out = _simulate_handler(run, req)
    except Exception as exc:  # noqa: BLE001 — AdapterError or unexpected
        from .adapters import AdapterError

        msg = getattr(exc, "message", None) or str(exc)
        code = "live_adapter_failed"
        if isinstance(exc, AdapterError):
            code = "live_adapter_denied" if exc.status_code == 403 else "live_adapter_failed"
        failed = _finish_run(
            run_id,
            tid=tid,
            status="failed",
            updates={
                "error_code": code,
                "result_summary": msg[:500],
                "result_detail": {"error": msg[:500]},
            },
            actor=actor,
        )
        _requests().update_one(
            merge_tenant_filter({"request_id": run["request_id"]}, tid),
            {
                "$set": {
                    "status": "failed",
                    "updated_at": _now(),
                    "updated_by": who,
                }
            },
        )
        try:
            refreshed = get_request(tenant_id=tid, request_id=run["request_id"])
            portal_notifications.notify_request_decision(
                tenant_id=tid,
                request={
                    **refreshed,
                    "change_status_snapshot": refreshed.get("change_status_snapshot")
                    or "failed",
                },
                decision="failed",
                actor=actor,
            )
        except Exception:  # noqa: BLE001
            pass
        return failed

    sync_outcome = {
        "cmdb_sync_status": "none",
        "component_id": req.get("component_id"),
        "cmdb_sync_error": None,
    }
    if not run.get("dry_run"):
        sync_outcome = _apply_cmdb_sync(
            tid=tid, req=req, run={**run, **handler_out}
        )

    finished = _finish_run(
        run_id,
        tid=tid,
        status="succeeded",
        updates={
            **handler_out,
            "cmdb_sync_status": sync_outcome["cmdb_sync_status"],
            "component_id": sync_outcome.get("component_id"),
            "error_code": None,
        },
        actor=actor,
    )

    req_updates: dict[str, Any] = {
        "status": "succeeded",
        "updated_at": _now(),
        "updated_by": who,
        "cmdb_sync_status": sync_outcome["cmdb_sync_status"],
        "cmdb_sync_error": sync_outcome.get("cmdb_sync_error"),
    }
    if sync_outcome.get("component_id"):
        req_updates["component_id"] = sync_outcome["component_id"]
    _requests().update_one(
        merge_tenant_filter({"request_id": run["request_id"]}, tid),
        {"$set": req_updates},
    )

    # Refresh request for notification payload.
    try:
        refreshed = get_request(tenant_id=tid, request_id=run["request_id"])
        portal_notifications.notify_request_decision(
            tenant_id=tid,
            request={
                **refreshed,
                "change_status_snapshot": refreshed.get("change_status_snapshot")
                or "executed",
            },
            decision="succeeded",
            actor=actor,
        )
    except Exception:  # noqa: BLE001 — never break tick
        pass

    return finished


def simulate_tick(
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Advance up to ``limit`` queued/running runs (SIMULATED + LIVE).

    Name kept for SP6 compatibility; SP10 also advances LIVE / DRY_RUN runs.
    """
    tid = require_tenant_id(tenant_id)
    lim = max(1, min(int(limit), 100))
    advanced: list[dict[str, Any]] = []

    # Phase 1: start queued runs.
    queued = list(
        _runs()
        .find(merge_tenant_filter({"status": "queued"}, tid))
        .sort([("created_at", 1)])
        .limit(lim)
    )
    for doc in queued:
        advanced.append(
            advance_run(doc["run_id"], tenant_id=tid, actor=actor)
        )

    # Phase 2: finish running runs (including those just started).
    remaining = lim
    running = list(
        _runs()
        .find(merge_tenant_filter({"status": "running"}, tid))
        .sort([("started_at", 1), ("created_at", 1)])
        .limit(remaining)
    )
    for doc in running:
        advanced.append(
            advance_run(doc["run_id"], tenant_id=tid, actor=actor)
        )

    modes = sorted(
        {
            str(item.get("execution_mode") or "SIMULATED")
            for item in advanced
        }
    )
    return {
        "advanced": len(advanced),
        "items": advanced,
        "execution_mode": modes[0] if len(modes) == 1 else "MIXED",
        "execution_modes": modes,
    }


def requeue_request(
    request_id: str,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
    dry_run: bool = False,
    collect_mode: str | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    req = get_request(tenant_id=tid, request_id=request_id)
    if req.get("status") not in ("approved", "failed", "succeeded", "queued"):
        raise ExecutionError(
            f"cannot requeue request in status '{req.get('status')}'",
            status_code=409,
        )
    updates: dict[str, Any] = {
        "status": "approved",
        "updated_at": _now(),
        "updated_by": _actor_name(actor),
    }
    if dry_run:
        updates["requested_execution_mode"] = "DRY_RUN"
    if collect_mode:
        updates["collect_mode"] = collect_mode
    _requests().update_one(
        merge_tenant_filter({"request_id": request_id}, tid),
        {"$set": updates},
    )
    return enqueue_execution(
        request_id, tenant_id=tid, actor=actor, force=True
    )
