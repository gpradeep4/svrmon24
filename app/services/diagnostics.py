"""Diagnostic engine service — DEMO/SIMULATED execution only."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from ..db import require_database
from ..diagnostics.profiles import EXECUTION_MODE, list_profiles, require_profile
from ..diagnostics.simulator import run_simulated_profile
from ..models.diagnostics import DiagnosticStartRequest
from ..serialization import serialize_document
from . import components as components_service
from . import dependencies as dependencies_service

COLLECTION = "diagnostic_history"


class DiagnosticError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _db_collection() -> Collection:
    coll = require_database()[COLLECTION]
    coll.create_index([("diagnostic_id", ASCENDING)], unique=True)
    coll.create_index([("component_id", ASCENDING)])
    coll.create_index([("profile_name", ASCENDING)])
    coll.create_index([("timestamp", DESCENDING)])
    return coll


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_diagnostic_id() -> str:
    return f"diag-{uuid.uuid4().hex[:12]}"


def list_diagnostic_profiles() -> dict[str, Any]:
    return {
        "execution_mode": EXECUTION_MODE,
        "demo_only": True,
        "profiles": list_profiles(),
        "notice": (
            "All diagnostics run in SIMULATED mode. Synthetic values are not real "
            "telemetry. Remote execution, shell, SQL, and network scanning are disabled."
        ),
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


def _dependency_context(component_id: str) -> dict[str, Any]:
    """Attach relevant dependency context from relationship traversal."""
    try:
        upstream = dependencies_service.get_direct_upstream(component_id)
        downstream = dependencies_service.get_direct_downstream(component_id)
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
            for e in (list(upstream.get("edges") or []) + list(downstream.get("edges") or []))[
                :20
            ]
        ],
        "source": "cmdb_relationships",
    }


def start_diagnostic(payload: DiagnosticStartRequest) -> dict[str, Any]:
    """Validate and run an approved profile in SIMULATED mode; persist history."""
    component = components_service.get_component(payload.component_id)
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

    if profile.get("execution_mode") != EXECUTION_MODE:
        raise DiagnosticError(
            "Only SIMULATED diagnostic profiles are permitted in this release",
            status_code=403,
        )

    now = _now()
    diagnostic_id = generate_diagnostic_id()
    checks = run_simulated_profile(
        component_id=payload.component_id,
        profile=profile,
    )
    ok_count = sum(1 for c in checks if c.get("status") == "ok")
    record: dict[str, Any] = {
        "diagnostic_id": diagnostic_id,
        "timestamp": now,
        "created_at": now,
        "execution_mode": EXECUTION_MODE,
        "profile_name": payload.profile_name,
        "component_id": payload.component_id,
        "component": _component_snapshot(component),
        "dependency_context": _dependency_context(payload.component_id),
        "checks": checks,
        "summary": {
            "overall_status": "ok" if ok_count == len(checks) else "warning",
            "check_count": len(checks),
            "ok_count": ok_count,
            "synthetic_check_count": sum(1 for c in checks if c.get("synthetic")),
        },
        "labels": {
            "demo": True,
            "simulated": True,
            "real_telemetry": False,
            "banner": "SIMULATED / SYNTHETIC DEMO OUTPUT — NOT REAL TELEMETRY",
        },
        "notes": payload.notes,
        "safety": {
            "remote_execution": False,
            "shell": False,
            "sql": False,
            "network_scan": False,
        },
    }

    _db_collection().insert_one(record)
    return serialize_document(record)  # type: ignore[return-value]


def get_diagnostic(diagnostic_id: str) -> dict[str, Any] | None:
    doc = _db_collection().find_one({"diagnostic_id": diagnostic_id})
    return serialize_document(doc)  # type: ignore[return-value]


def list_diagnostics(
    *,
    component_id: str | None = None,
    profile_name: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    query: dict[str, Any] = {}
    if component_id:
        query["component_id"] = component_id
    if profile_name:
        query["profile_name"] = profile_name

    coll = _db_collection()
    total = coll.count_documents(query)
    cursor = (
        coll.find(query)
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
    }
