"""File Monitoring service — DEMO/SIMULATED only (tenant-scoped).

No live filesystem watching. All targets and version events are synthetic
demo data until live probes are explicitly approved.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from ..db import require_database
from ..serialization import serialize_document
from ..tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id, tenant_filter

TARGETS_COLLECTION = "file_watch_targets"
EVENTS_COLLECTION = "file_version_events"

EXECUTION_MODE = "SIMULATED"
DATA_SOURCE = "SYNTHETIC_DEMO"
SIMULATED_NOTE = "Synthetic demo event — not a live filesystem change."
BANNER = (
    "SIMULATED / SYNTHETIC_DEMO — File Monitoring does not watch real paths. "
    "No live filesystem probes until explicitly approved."
)


class FileMonitoringError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _targets() -> Collection:
    coll = require_database()[TARGETS_COLLECTION]
    coll.create_index(
        [("tenant_id", ASCENDING), ("watch_id", ASCENDING)],
        unique=True,
        name="tenant_watch_id_unique",
    )
    coll.create_index(
        [("tenant_id", ASCENDING), ("path", ASCENDING)],
        name="tenant_path_idx",
    )
    coll.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")
    return coll


def _events() -> Collection:
    coll = require_database()[EVENTS_COLLECTION]
    coll.create_index(
        [("tenant_id", ASCENDING), ("event_id", ASCENDING)],
        unique=True,
        name="tenant_event_id_unique",
    )
    coll.create_index(
        [("tenant_id", ASCENDING), ("watch_id", ASCENDING), ("version", ASCENDING)],
        name="tenant_watch_version_idx",
    )
    coll.create_index(
        [("tenant_id", ASCENDING), ("changed_at", ASCENDING)],
        name="tenant_changed_at_idx",
    )
    coll.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")
    return coll


def _demo_seed_payload(*, tenant_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Stable SIMULATED demo targets + version events for a tenant."""
    tid = require_tenant_id(tenant_id)
    base = _now().replace(microsecond=0) - timedelta(days=14)
    targets = [
        {
            "watch_id": "fw-demo-nginx-conf",
            "path": "/etc/nginx/nginx.conf",
            "label": "Nginx main config",
            "host": "demo-srv-web01",
            "component_id": "demo-srv-web01",
            "status": "active",
            "execution_mode": EXECUTION_MODE,
            "latest_version": 4,
            "latest_actor": "ops.alice",
            "latest_changed_at": base + timedelta(days=12, hours=9),
            "notes": "[demo-seed] SIMULATED watch target",
            "created_at": base,
            "updated_at": base + timedelta(days=12, hours=9),
        },
        {
            "watch_id": "fw-demo-app-env",
            "path": "/opt/billing/config/app.env",
            "label": "Billing app env",
            "host": "demo-srv-app01",
            "component_id": "demo-srv-app01",
            "status": "active",
            "execution_mode": EXECUTION_MODE,
            "latest_version": 3,
            "latest_actor": "svc.deploy",
            "latest_changed_at": base + timedelta(days=10, hours=16),
            "notes": "[demo-seed] SIMULATED watch target",
            "created_at": base + timedelta(days=1),
            "updated_at": base + timedelta(days=10, hours=16),
        },
        {
            "watch_id": "fw-demo-ora-tns",
            "path": "/u01/app/oracle/product/19.0.0/network/admin/tnsnames.ora",
            "label": "Oracle TNS names",
            "host": "demo-db-orders",
            "component_id": "demo-db-orders",
            "status": "paused",
            "execution_mode": EXECUTION_MODE,
            "latest_version": 2,
            "latest_actor": "dba.chen",
            "latest_changed_at": base + timedelta(days=5, hours=11),
            "notes": "[demo-seed] SIMULATED watch target (paused)",
            "created_at": base + timedelta(days=2),
            "updated_at": base + timedelta(days=5, hours=11),
        },
        {
            "watch_id": "fw-demo-sudoers",
            "path": "/etc/sudoers.d/svrmon24",
            "label": "SVRMON24 sudoers drop-in",
            "host": "demo-srv-web01",
            "component_id": "demo-srv-web01",
            "status": "active",
            "execution_mode": EXECUTION_MODE,
            "latest_version": 2,
            "latest_actor": "sec.jordan",
            "latest_changed_at": base + timedelta(days=8, hours=14),
            "notes": "[demo-seed] SIMULATED watch target",
            "created_at": base + timedelta(days=3),
            "updated_at": base + timedelta(days=8, hours=14),
        },
    ]
    events = [
        # nginx.conf
        {
            "event_id": "fve-demo-nginx-v1",
            "watch_id": "fw-demo-nginx-conf",
            "path": "/etc/nginx/nginx.conf",
            "version": 1,
            "change_kind": "created",
            "actor": "ops.alice",
            "actor_type": "user",
            "changed_at": base + timedelta(days=1),
            "summary": "Initial SIMULATED baseline capture",
            "content_hash": "sim-sha256:nginx-v1",
            "size_bytes": 4200,
        },
        {
            "event_id": "fve-demo-nginx-v2",
            "watch_id": "fw-demo-nginx-conf",
            "path": "/etc/nginx/nginx.conf",
            "version": 2,
            "change_kind": "modified",
            "actor": "ops.alice",
            "actor_type": "user",
            "changed_at": base + timedelta(days=4, hours=8),
            "summary": "Raised worker_connections (SIMULATED)",
            "content_hash": "sim-sha256:nginx-v2",
            "size_bytes": 4288,
        },
        {
            "event_id": "fve-demo-nginx-v3",
            "watch_id": "fw-demo-nginx-conf",
            "path": "/etc/nginx/nginx.conf",
            "version": 3,
            "change_kind": "modified",
            "actor": "svc.deploy",
            "actor_type": "service",
            "changed_at": base + timedelta(days=9, hours=15),
            "summary": "TLS cipher suite update via pipeline (SIMULATED)",
            "content_hash": "sim-sha256:nginx-v3",
            "size_bytes": 4350,
        },
        {
            "event_id": "fve-demo-nginx-v4",
            "watch_id": "fw-demo-nginx-conf",
            "path": "/etc/nginx/nginx.conf",
            "version": 4,
            "change_kind": "modified",
            "actor": "ops.alice",
            "actor_type": "user",
            "changed_at": base + timedelta(days=12, hours=9),
            "summary": "Added rate-limit zone for /api (SIMULATED)",
            "content_hash": "sim-sha256:nginx-v4",
            "size_bytes": 4512,
        },
        # app.env
        {
            "event_id": "fve-demo-env-v1",
            "watch_id": "fw-demo-app-env",
            "path": "/opt/billing/config/app.env",
            "version": 1,
            "change_kind": "created",
            "actor": "dev.sam",
            "actor_type": "user",
            "changed_at": base + timedelta(days=2),
            "summary": "Initial env template (SIMULATED)",
            "content_hash": "sim-sha256:env-v1",
            "size_bytes": 860,
        },
        {
            "event_id": "fve-demo-env-v2",
            "watch_id": "fw-demo-app-env",
            "path": "/opt/billing/config/app.env",
            "version": 2,
            "change_kind": "modified",
            "actor": "svc.deploy",
            "actor_type": "service",
            "changed_at": base + timedelta(days=6, hours=18),
            "summary": "Rotated DB pool size (SIMULATED)",
            "content_hash": "sim-sha256:env-v2",
            "size_bytes": 872,
        },
        {
            "event_id": "fve-demo-env-v3",
            "watch_id": "fw-demo-app-env",
            "path": "/opt/billing/config/app.env",
            "version": 3,
            "change_kind": "modified",
            "actor": "svc.deploy",
            "actor_type": "service",
            "changed_at": base + timedelta(days=10, hours=16),
            "summary": "Feature flag BILLING_V2=true (SIMULATED)",
            "content_hash": "sim-sha256:env-v3",
            "size_bytes": 890,
        },
        # tnsnames
        {
            "event_id": "fve-demo-tns-v1",
            "watch_id": "fw-demo-ora-tns",
            "path": "/u01/app/oracle/product/19.0.0/network/admin/tnsnames.ora",
            "version": 1,
            "change_kind": "created",
            "actor": "dba.chen",
            "actor_type": "user",
            "changed_at": base + timedelta(days=3),
            "summary": "Baseline TNS entry (SIMULATED)",
            "content_hash": "sim-sha256:tns-v1",
            "size_bytes": 512,
        },
        {
            "event_id": "fve-demo-tns-v2",
            "watch_id": "fw-demo-ora-tns",
            "path": "/u01/app/oracle/product/19.0.0/network/admin/tnsnames.ora",
            "version": 2,
            "change_kind": "modified",
            "actor": "dba.chen",
            "actor_type": "user",
            "changed_at": base + timedelta(days=5, hours=11),
            "summary": "Added standby alias (SIMULATED)",
            "content_hash": "sim-sha256:tns-v2",
            "size_bytes": 640,
        },
        # sudoers
        {
            "event_id": "fve-demo-sudo-v1",
            "watch_id": "fw-demo-sudoers",
            "path": "/etc/sudoers.d/svrmon24",
            "version": 1,
            "change_kind": "created",
            "actor": "sec.jordan",
            "actor_type": "user",
            "changed_at": base + timedelta(days=3, hours=10),
            "summary": "Least-privilege agent drop-in (SIMULATED)",
            "content_hash": "sim-sha256:sudo-v1",
            "size_bytes": 220,
        },
        {
            "event_id": "fve-demo-sudo-v2",
            "watch_id": "fw-demo-sudoers",
            "path": "/etc/sudoers.d/svrmon24",
            "version": 2,
            "change_kind": "permission",
            "actor": "sec.jordan",
            "actor_type": "user",
            "changed_at": base + timedelta(days=8, hours=14),
            "summary": "Mode tightened to 0440 (SIMULATED)",
            "content_hash": "sim-sha256:sudo-v2",
            "size_bytes": 220,
        },
    ]
    stamped_targets = [stamp_tenant_id(dict(t), tenant_id=tid) for t in targets]
    stamped_events: list[dict[str, Any]] = []
    for ev in events:
        doc = dict(ev)
        doc["execution_mode"] = EXECUTION_MODE
        doc["data_source"] = DATA_SOURCE
        doc["note"] = SIMULATED_NOTE
        doc["created_at"] = doc["changed_at"]
        stamped_events.append(stamp_tenant_id(doc, tenant_id=tid))
    return stamped_targets, stamped_events


def ensure_simulated_seed(*, tenant_id: str) -> dict[str, Any]:
    """Idempotently insert demo SIMULATED targets + events for a tenant."""
    tid = require_tenant_id(tenant_id)
    targets_coll = _targets()
    events_coll = _events()
    existing = targets_coll.count_documents(tenant_filter(tid))
    if existing > 0:
        return {
            "seeded": False,
            "reason": "targets_already_present",
            "tenant_id": tid,
            "targets": existing,
            "events": events_coll.count_documents(tenant_filter(tid)),
        }

    targets, events = _demo_seed_payload(tenant_id=tid)
    if targets:
        targets_coll.insert_many(targets)
    if events:
        events_coll.insert_many(events)
    return {
        "seeded": True,
        "tenant_id": tid,
        "targets": len(targets),
        "events": len(events),
        "execution_mode": EXECUTION_MODE,
    }


def wipe_demo_for_tenant(*, tenant_id: str) -> dict[str, int]:
    """Remove demo-* / fw-demo / fve-demo file monitoring rows for a tenant."""
    tid = require_tenant_id(tenant_id)
    demo_filter = merge_tenant_filter(
        {
            "$or": [
                {"watch_id": {"$regex": "^fw-demo-"}},
                {"event_id": {"$regex": "^fve-demo-"}},
                {"notes": {"$regex": "\\[demo-seed\\]"}},
            ]
        },
        tid,
    )
    return {
        "targets": int(_targets().delete_many(demo_filter).deleted_count),
        "events": int(
            _events()
            .delete_many(
                merge_tenant_filter(
                    {
                        "$or": [
                            {"event_id": {"$regex": "^fve-demo-"}},
                            {"watch_id": {"$regex": "^fw-demo-"}},
                        ]
                    },
                    tid,
                )
            )
            .deleted_count
        ),
    }


def module_meta() -> dict[str, Any]:
    return {
        "module": "file_monitoring",
        "execution_mode": EXECUTION_MODE,
        "demo_only": True,
        "live_watching": False,
        "banner": BANNER,
        "notice": (
            "File Monitoring v1 is SIMULATED. Watched paths and version history "
            "are synthetic demo data. Live filesystem watching is not enabled."
        ),
    }


def list_targets(
    *,
    tenant_id: str,
    q: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 25,
    ensure_seed: bool = True,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if ensure_seed:
        ensure_simulated_seed(tenant_id=tid)

    query: dict[str, Any] = {}
    if status:
        query["status"] = status.strip().lower()
    if q:
        term = q.strip()
        if term:
            query["$or"] = [
                {"path": {"$regex": term, "$options": "i"}},
                {"label": {"$regex": term, "$options": "i"}},
                {"host": {"$regex": term, "$options": "i"}},
                {"watch_id": {"$regex": term, "$options": "i"}},
                {"latest_actor": {"$regex": term, "$options": "i"}},
            ]

    coll = _targets()
    filt = merge_tenant_filter(query, tid)
    total = coll.count_documents(filt)
    skip = max(0, (page - 1) * page_size)
    cursor = (
        coll.find(filt)
        .sort([("latest_changed_at", DESCENDING), ("path", ASCENDING)])
        .skip(skip)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        **module_meta(),
        "tenant_id": tid,
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": items,
    }


def get_target(*, tenant_id: str, watch_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    ensure_simulated_seed(tenant_id=tid)
    doc = _targets().find_one(
        merge_tenant_filter({"watch_id": watch_id.strip()}, tid)
    )
    return serialize_document(doc)


def list_versions(
    *,
    tenant_id: str,
    watch_id: str,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    ensure_simulated_seed(tenant_id=tid)
    target = get_target(tenant_id=tid, watch_id=watch_id)
    if target is None:
        raise FileMonitoringError(
            f"Watch target '{watch_id}' not found", status_code=404
        )

    filt = merge_tenant_filter({"watch_id": watch_id.strip()}, tid)
    coll = _events()
    total = coll.count_documents(filt)
    skip = max(0, (page - 1) * page_size)
    cursor = (
        coll.find(filt)
        .sort([("version", DESCENDING)])
        .skip(skip)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        **module_meta(),
        "tenant_id": tid,
        "watch_id": watch_id,
        "target": target,
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": items,
    }


def get_version_event(*, tenant_id: str, event_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    ensure_simulated_seed(tenant_id=tid)
    doc = _events().find_one(
        merge_tenant_filter({"event_id": event_id.strip()}, tid)
    )
    return serialize_document(doc)
