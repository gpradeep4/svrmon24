"""Diagnostics service — DEMO/SIMULATED only (tenant-scoped, monitor DB).

M8: ``diagnostic_history`` lives in ``svrmon-monitor``. When the monitor DB has
no rows for a tenant, data is migrated (copied) from the legacy CMDB collection
once. ``/api/diagnostics`` routes keep working via the CMDB shim.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from ...cmdb.diagnostics.profiles import EXECUTION_MODE, list_profiles, require_profile
from ...cmdb.diagnostics.simulator import run_simulated_profile
from ...cmdb.models.diagnostics import DiagnosticStartRequest
from ...cmdb.services import components as components_service
from ...cmdb.services import dependencies as dependencies_service
from ...config import get_settings
from ...db import get_database, require_monitor_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id, tenant_filter
from .indexes import ensure_monitor_indexes

COLLECTION = "diagnostic_history"


def _monitor_db_name() -> str:
    return get_settings().monitor_database_name


class DiagnosticError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _monitor_db():
    ensure_monitor_indexes()
    return require_monitor_database()


def _db_collection() -> Collection:
    return _monitor_db()[COLLECTION]


def _cmdb_collection() -> Collection:
    return get_database()[COLLECTION]


def _strip_id(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    out.pop("_id", None)
    return out


def migrate_tenant_from_cmdb(*, tenant_id: str) -> dict[str, Any]:
    """Copy CMDB diagnostic_history into monitor DB when monitor is empty.

    Idempotent: no-op when the monitor DB already has rows for the tenant.
    Does not delete CMDB source rows (compat dual-read window).
    """
    tid = require_tenant_id(tenant_id)
    coll = _db_collection()
    existing = coll.count_documents(tenant_filter(tid))
    if existing > 0:
        return {
            "migrated": False,
            "reason": "monitor_already_populated",
            "tenant_id": tid,
            "diagnostics": existing,
        }

    filt = tenant_filter(tid)
    cmdb_rows = list(_cmdb_collection().find(filt))
    if not cmdb_rows:
        return {
            "migrated": False,
            "reason": "cmdb_empty",
            "tenant_id": tid,
            "diagnostics": 0,
        }

    inserted = [_strip_id(doc) for doc in cmdb_rows]
    coll.insert_many(inserted)
    return {
        "migrated": True,
        "tenant_id": tid,
        "diagnostics": len(inserted),
        "source": "cmdb",
    }


def _ensure_monitor_data(*, tenant_id: str) -> None:
    migrate_tenant_from_cmdb(tenant_id=tenant_id)


def generate_diagnostic_id() -> str:
    return f"diag-{uuid.uuid4().hex[:12]}"


def list_diagnostic_profiles(*, tenant_id: str | None = None) -> dict[str, Any]:
    from ...services import live_settings as live_settings_service

    live_on = False
    if tenant_id:
        live_on = live_settings_service.diagnostics_live_allowed(tenant_id=tenant_id)
    return {
        "execution_mode": "LIVE" if live_on else EXECUTION_MODE,
        "demo_only": not live_on,
        "live_available": live_on,
        "profiles": list_profiles(),
        "notice": (
            "LIVE diagnostics are available for this tenant (platform + tenant "
            "gates on). Pass prefer_live=true to run the LIVE path. Shell/SQL/"
            "remote command payloads remain blocked."
            if live_on
            else (
                "Diagnostics default to SIMULATED mode. Synthetic values are not "
                "real telemetry. Enable DIAGNOSTICS_LIVE_ENABLED plus tenant "
                "diagnostics_live_opt_in (Configuration → Live / Runtime) for LIVE. "
                "Remote shell, SQL, and network scanning stay disabled."
            )
        ),
        "database": _monitor_db_name(),
    }


def _component_snapshot(component: dict[str, Any]) -> dict[str, Any]:
    return {
        "component_id": component.get("component_id"),
        "component_type": component.get("component_type"),
        "name": component.get("name"),
        "environment": component.get("environment"),
        "status": component.get("status"),
        "hostname": component.get("hostname"),
        "product_type": component.get("product_type"),
        "product_version": component.get("product_version"),
        "os_family": component.get("os_family"),
        "os_version": component.get("os_version"),
    }


def _dependency_context(component_id: str, *, tenant_id: str) -> dict[str, Any]:
    """Attach relevant dependency context from relationship traversal."""
    try:
        upstream = dependencies_service.get_direct_upstream(
            component_id, tenant_id=tenant_id
        )
        downstream = dependencies_service.get_direct_downstream(
            component_id, tenant_id=tenant_id
        )
    except dependencies_service.DependencyError:
        return {
            "upstream_direct": [],
            "downstream_direct": [],
            "edges_sample": [],
            "note": "Dependency context unavailable for this component.",
            "source": "cmdb_relationships",
        }
    return {
        "upstream_direct": [
            {
                "component_id": n.get("component_id"),
                "component_type": n.get("component_type"),
                "name": n.get("name"),
                "relationship_hint": "upstream",
            }
            for n in upstream.get("nodes") or []
            if not n.get("is_selected")
        ],
        "downstream_direct": [
            {
                "component_id": n.get("component_id"),
                "component_type": n.get("component_type"),
                "name": n.get("name"),
                "relationship_hint": "downstream",
            }
            for n in downstream.get("nodes") or []
            if not n.get("is_selected")
        ],
        "edges_sample": [
            {
                "relationship_id": e.get("relationship_id"),
                "relationship_type": e.get("relationship_type"),
                "protocol": e.get("protocol"),
                "source_port": e.get("source_port"),
                "target_port": e.get("target_port"),
            }
            for e in (
                list(upstream.get("edges") or []) + list(downstream.get("edges") or [])
            )[:20]
        ],
        "source": "cmdb_relationships",
    }


def count_diagnostics(*, tenant_id: str) -> int:
    tid = require_tenant_id(tenant_id)
    _ensure_monitor_data(tenant_id=tid)
    return int(_db_collection().count_documents(tenant_filter(tid)))


def enforce_diagnostics_retention(*, tenant_id: str) -> int:
    """Trim oldest diagnostic_history rows over ``max_diagnostic_runs``."""
    from ...services import entitlements as entitlements_service

    tid = require_tenant_id(tenant_id)
    limit = entitlements_service.diagnostic_run_limit(tid)
    if limit is None:
        return 0
    _ensure_monitor_data(tenant_id=tid)
    coll = _db_collection()
    total = coll.count_documents(tenant_filter(tid))
    if total <= limit:
        return 0
    excess = total - limit
    oldest = list(
        coll.find(tenant_filter(tid), {"_id": 1})
        .sort([("timestamp", ASCENDING), ("_id", ASCENDING)])
        .limit(excess)
    )
    if not oldest:
        return 0
    ids = [row["_id"] for row in oldest]
    result = coll.delete_many({"_id": {"$in": ids}})
    return int(result.deleted_count)


def _live_connectivity_check(component: dict[str, Any]) -> dict[str, Any]:
    """Best-effort TCP reachability when LIVE gates are open (no shell/SQL)."""
    import socket

    host = str(component.get("hostname") or component.get("name") or "").strip()
    if not host:
        return {
            "check_id": "live_connectivity",
            "label": "LIVE connectivity",
            "metric_kind": "connectivity",
            "unit": "status",
            "value": "skipped",
            "status": "warning",
            "synthetic": False,
            "data_source": "LIVE",
            "note": "No hostname on CI — LIVE connectivity skipped.",
        }
    port = 22
    try:
        with socket.create_connection((host, port), timeout=2.0):
            reachable = True
    except OSError as exc:
        return {
            "check_id": "live_connectivity",
            "label": "LIVE connectivity",
            "metric_kind": "connectivity",
            "unit": "status",
            "value": "unreachable",
            "status": "warning",
            "synthetic": False,
            "data_source": "LIVE",
            "note": f"TCP {host}:{port} failed ({exc}). Shell/SQL still disabled.",
        }
    return {
        "check_id": "live_connectivity",
        "label": "LIVE connectivity",
        "metric_kind": "connectivity",
        "unit": "status",
        "value": "reachable" if reachable else "unreachable",
        "status": "ok" if reachable else "warning",
        "synthetic": False,
        "data_source": "LIVE",
        "note": f"TCP connect to {host}:{port} succeeded. Shell/SQL still disabled.",
    }


def start_diagnostic(
    payload: DiagnosticStartRequest, *, tenant_id: str
) -> dict[str, Any]:
    """Validate and run an approved profile; SIMULATED by default, LIVE when gated."""
    tid = require_tenant_id(tenant_id)
    _ensure_monitor_data(tenant_id=tid)

    from ...services import entitlements as entitlements_service
    from ...services import live_settings as live_settings_service
    from ...services.entitlements import EntitlementError

    prefer_live = bool(getattr(payload, "prefer_live", False))
    if prefer_live and not live_settings_service.diagnostics_live_allowed(
        tenant_id=tid
    ):
        raise DiagnosticError(
            live_settings_service.DIAGNOSTICS_LIVE_DISABLED,
            status_code=403,
        )

    try:
        entitlements_service.assert_can_run_diagnostic(tid)
    except EntitlementError as exc:
        raise DiagnosticError(exc.message, status_code=exc.status_code) from exc

    component = components_service.get_component(payload.component_id, tenant_id=tid)
    if component is None:
        raise DiagnosticError(
            f"Unknown component_id '{payload.component_id}'",
            status_code=404,
        )

    try:
        profile = require_profile(payload.profile_name)
    except KeyError as exc:
        raise DiagnosticError(
            f"Unknown or invalid profile_name '{payload.profile_name}'",
            status_code=422,
        ) from exc
    except PermissionError as exc:
        raise DiagnosticError(str(exc), status_code=403) from exc

    allowed_types = set(profile.get("allowed_component_types") or [])
    ctype = component.get("component_type")
    if allowed_types and ctype not in allowed_types:
        raise DiagnosticError(
            f"Profile '{payload.profile_name}' does not support component_type '{ctype}'",
            status_code=422,
        )

    # Profiles remain SIMULATED templates; LIVE adds a gated connectivity check.
    if profile.get("execution_mode") not in {EXECUTION_MODE, "SIMULATED", "LIVE"}:
        raise DiagnosticError(
            "Only approved diagnostic profiles are permitted",
            status_code=403,
        )

    now = _now()
    diagnostic_id = generate_diagnostic_id()
    checks = run_simulated_profile(
        component_id=payload.component_id,
        profile=profile,
    )
    execution_mode = EXECUTION_MODE
    if prefer_live:
        execution_mode = "LIVE"
        checks = list(checks) + [_live_connectivity_check(component)]
    ok_count = sum(1 for c in checks if c.get("status") == "ok")
    live = execution_mode == "LIVE"
    record: dict[str, Any] = {
        "diagnostic_id": diagnostic_id,
        "timestamp": now,
        "created_at": now,
        "execution_mode": execution_mode,
        "profile_name": payload.profile_name,
        "component_id": payload.component_id,
        "component": _component_snapshot(component),
        "dependency_context": _dependency_context(payload.component_id, tenant_id=tid),
        "checks": checks,
        "summary": {
            "overall_status": "ok" if ok_count == len(checks) else "warning",
            "check_count": len(checks),
            "ok_count": ok_count,
            "synthetic_check_count": sum(1 for c in checks if c.get("synthetic")),
        },
        "labels": {
            "demo": not live,
            "simulated": not live,
            "real_telemetry": live,
            "banner": (
                "LIVE DIAGNOSTIC — limited connectivity probe; shell/SQL still disabled"
                if live
                else "SIMULATED / SYNTHETIC DEMO OUTPUT — NOT REAL TELEMETRY"
            ),
        },
        "notes": payload.notes,
        "safety": {
            "remote_execution": False,
            "shell": False,
            "sql": False,
            "network_scan": False,
            "live_connectivity": live,
        },
    }
    stamp_tenant_id(record, tenant_id=tid)

    _db_collection().insert_one(record)
    enforce_diagnostics_retention(tenant_id=tid)
    return serialize_document(record)  # type: ignore[return-value]


def get_diagnostic(diagnostic_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    _ensure_monitor_data(tenant_id=tid)
    doc = _db_collection().find_one(
        {"diagnostic_id": diagnostic_id, **tenant_filter(tid)}
    )
    return serialize_document(doc)  # type: ignore[return-value]


def attach_ai_analysis(
    diagnostic_id: str, analysis: dict[str, Any], *, tenant_id: str
) -> dict[str, Any]:
    """Store latest analysis and append to history on the diagnostic record."""
    tid = require_tenant_id(tenant_id)
    _ensure_monitor_data(tenant_id=tid)
    coll = _db_collection()
    existing = coll.find_one({"diagnostic_id": diagnostic_id, **tenant_filter(tid)})
    if existing is None:
        raise DiagnosticError(
            f"Diagnostic '{diagnostic_id}' not found",
            status_code=404,
        )
    history = list(existing.get("ai_analysis_history") or [])
    history.append(analysis)
    coll.update_one(
        {"diagnostic_id": diagnostic_id, **tenant_filter(tid)},
        {
            "$set": {
                "ai_analysis": analysis,
                "ai_analysis_history": history,
                "updated_at": _now(),
            }
        },
    )
    doc = get_diagnostic(diagnostic_id, tenant_id=tid)
    assert doc is not None
    return doc


def count_ollama_analyses(*, tenant_id: str) -> int:
    """Count generative AI analysis history entries for a tenant."""
    tid = require_tenant_id(tenant_id)
    _ensure_monitor_data(tenant_id=tid)
    coll = _db_collection()
    pipeline = [
        {"$match": tenant_filter(tid)},
        {
            "$unwind": {
                "path": "$ai_analysis_history",
                "preserveNullAndEmptyArrays": False,
            }
        },
        {
            "$match": {
                "ai_analysis_history.source": {
                    "$in": ["ollama", "cloud_suggestion"],
                }
            }
        },
        {"$count": "total"},
    ]
    rows = list(coll.aggregate(pipeline))
    if not rows:
        return 0
    return int(rows[0].get("total") or 0)


def list_diagnostics(
    *,
    tenant_id: str,
    component_id: str | None = None,
    profile_name: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _ensure_monitor_data(tenant_id=tid)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    query: dict[str, Any] = {}
    if component_id:
        query["component_id"] = component_id
    if profile_name:
        query["profile_name"] = profile_name

    scoped = merge_tenant_filter(query, tid)
    coll = _db_collection()
    total = coll.count_documents(scoped)
    cursor = (
        coll.find(scoped)
        .sort("timestamp", DESCENDING)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "execution_mode": EXECUTION_MODE,
        "items": items,
        "tenant_id": tid,
        "database": _monitor_db_name(),
    }
