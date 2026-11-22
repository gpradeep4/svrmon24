"""File Monitoring service — SIMULATED default; LIVE watch modes (L6).

SIMULATED seed / version history remain the default. Live modes
(``AGENT`` / ``AGENTLESS_POLL``) are fail-closed behind ``file_watch_live``.

M3: collections live in ``svrmon-monitor``. When the monitor DB has no rows for
a tenant, data is migrated (copied) from the legacy CMDB collections once.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection

from ...config import Settings, get_settings
from ...db import get_database, require_monitor_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id, tenant_filter
from ..models.literals import WATCH_MODES
from .egress import EgressDenied, assert_egress_allowed, host_from_endpoint
from .indexes import ensure_monitor_indexes
from .live_gates import live_allowed

TARGETS_COLLECTION = "file_watch_targets"
EVENTS_COLLECTION = "file_version_events"

EXECUTION_MODE = "SIMULATED"
DATA_SOURCE = "SYNTHETIC_DEMO"
SIMULATED_NOTE = "Synthetic demo event — not a live filesystem change."
BANNER = (
    "SIMULATED / SYNTHETIC_DEMO — File Monitoring does not watch real paths by "
    "default. Set watch_mode=AGENT or AGENTLESS_POLL when live gates are on."
)

DEFAULT_POLL_INTERVAL = 60
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 86400
OS_WATCHERS = frozenset(
    {"inotify", "readdirectorychanges", "fsevents", "kqueue_or_poll"}
)

# Test double hook for agentless checksum polls (monkeypatch in tests).
ChecksumFetcher = Callable[..., dict[str, Any]]
_checksum_fetcher: ChecksumFetcher | None = None


def set_checksum_fetcher(fetcher: ChecksumFetcher | None) -> None:
    """Install or clear the agentless poll checksum fetcher (tests / lab)."""
    global _checksum_fetcher
    _checksum_fetcher = fetcher


class FileMonitoringError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _monitor_db():
    ensure_monitor_indexes()
    return require_monitor_database()


def _targets() -> Collection:
    return _monitor_db()[TARGETS_COLLECTION]


def _events() -> Collection:
    return _monitor_db()[EVENTS_COLLECTION]


def _cmdb_targets() -> Collection:
    return get_database()[TARGETS_COLLECTION]


def _cmdb_events() -> Collection:
    return get_database()[EVENTS_COLLECTION]


def _strip_id(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    out.pop("_id", None)
    return out


def migrate_tenant_from_cmdb(*, tenant_id: str) -> dict[str, Any]:
    """Copy CMDB file-monitoring rows into monitor DB when monitor is empty.

    Idempotent: no-op when the monitor DB already has targets for the tenant.
    Does not delete CMDB source rows (compat dual-read window).
    """
    tid = require_tenant_id(tenant_id)
    targets_coll = _targets()
    events_coll = _events()
    existing = targets_coll.count_documents(tenant_filter(tid))
    if existing > 0:
        return {
            "migrated": False,
            "reason": "monitor_already_populated",
            "tenant_id": tid,
            "targets": existing,
            "events": events_coll.count_documents(tenant_filter(tid)),
        }

    filt = tenant_filter(tid)
    cmdb_targets = list(_cmdb_targets().find(filt))
    if not cmdb_targets:
        return {
            "migrated": False,
            "reason": "cmdb_empty",
            "tenant_id": tid,
            "targets": 0,
            "events": 0,
        }

    cmdb_events = list(_cmdb_events().find(filt))
    inserted_targets = [_strip_id(doc) for doc in cmdb_targets]
    inserted_events = [_strip_id(doc) for doc in cmdb_events]
    if inserted_targets:
        targets_coll.insert_many(inserted_targets)
    if inserted_events:
        events_coll.insert_many(inserted_events)
    return {
        "migrated": True,
        "tenant_id": tid,
        "targets": len(inserted_targets),
        "events": len(inserted_events),
        "source": "cmdb",
    }


def _ensure_monitor_data(*, tenant_id: str) -> None:
    """Migrate from CMDB if needed, then leave seed to callers."""
    migrate_tenant_from_cmdb(tenant_id=tenant_id)


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
            "watch_mode": "SIMULATED",
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
            "watch_mode": "SIMULATED",
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
            "watch_mode": "SIMULATED",
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
            "watch_mode": "SIMULATED",
            "latest_version": 2,
            "latest_actor": "sec.jordan",
            "latest_changed_at": base + timedelta(days=8, hours=14),
            "notes": "[demo-seed] SIMULATED watch target",
            "created_at": base + timedelta(days=3),
            "updated_at": base + timedelta(days=8, hours=14),
        },
    ]
    events = [
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
    _ensure_monitor_data(tenant_id=tid)
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
    """Remove demo-* / fw-demo / fve-demo file monitoring rows for a tenant.

    Clears both monitor DB (canonical) and leftover CMDB rows from pre-M3.
    """
    tid = require_tenant_id(tenant_id)
    demo_target_filter = merge_tenant_filter(
        {
            "$or": [
                {"watch_id": {"$regex": "^fw-demo-"}},
                {"event_id": {"$regex": "^fve-demo-"}},
                {"notes": {"$regex": "\\[demo-seed\\]"}},
            ]
        },
        tid,
    )
    demo_event_filter = merge_tenant_filter(
        {
            "$or": [
                {"event_id": {"$regex": "^fve-demo-"}},
                {"watch_id": {"$regex": "^fw-demo-"}},
            ]
        },
        tid,
    )
    monitor_targets = int(_targets().delete_many(demo_target_filter).deleted_count)
    monitor_events = int(_events().delete_many(demo_event_filter).deleted_count)
    # Best-effort CMDB leftover cleanup during dual-read window.
    try:
        cmdb_targets = int(_cmdb_targets().delete_many(demo_target_filter).deleted_count)
        cmdb_events = int(_cmdb_events().delete_many(demo_event_filter).deleted_count)
    except Exception:  # noqa: BLE001 — CMDB wipe must not block monitor wipe
        cmdb_targets = 0
        cmdb_events = 0
    return {
        "targets": monitor_targets + cmdb_targets,
        "events": monitor_events + cmdb_events,
        "monitor_targets": monitor_targets,
        "monitor_events": monitor_events,
        "cmdb_targets": cmdb_targets,
        "cmdb_events": cmdb_events,
    }


def module_meta(
    *,
    settings: Settings | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    tid = (tenant_id or "").strip()
    live_ok = False
    if tid:
        live_ok = live_allowed(
            tenant_id=tid, capability="file_watch_live", settings=cfg
        )
    return {
        "module": "file_monitoring",
        "execution_mode": EXECUTION_MODE,
        "demo_only": not live_ok,
        "live_watching": live_ok,
        "watch_modes": list(WATCH_MODES),
        "os_watchers": sorted(OS_WATCHERS),
        "banner": BANNER,
        "notice": (
            "File Monitoring defaults to SIMULATED. Operators may set "
            "watch_mode=AGENT (OS watcher via agent ingest) or "
            "AGENTLESS_POLL (HTTP ETag/checksum where feasible) when "
            "platform + tenant live gates allow file_watch_live. "
            "Data is stored in the Monitoring database."
        ),
        "files_api": "/api/monitor/files/watches",
        "database": cfg.monitor_database_name,
        "monitor_database": cfg.monitor_database_name,
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
    else:
        _ensure_monitor_data(tenant_id=tid)

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
        **module_meta(tenant_id=tid),
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
        **module_meta(tenant_id=tid),
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


def _new_event_id() -> str:
    return f"fve-{uuid.uuid4().hex[:12]}"


def patch_watch(
    *,
    tenant_id: str,
    watch_id: str,
    payload: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Update watch_mode / agent / agentless poll fields (L6).

    Switching to AGENT or AGENTLESS_POLL requires ``file_watch_live``.
    SIMULATED mode is always allowed (fail-open for demo path).
    """
    tid = require_tenant_id(tenant_id)
    cfg = settings or get_settings()
    ensure_simulated_seed(tenant_id=tid)
    wid = watch_id.strip()
    existing = _targets().find_one(merge_tenant_filter({"watch_id": wid}, tid))
    if existing is None:
        raise FileMonitoringError(f"Watch target '{wid}' not found", status_code=404)

    updates: dict[str, Any] = {"updated_at": _now()}
    mode = payload.get("watch_mode")
    if mode is not None:
        mode_s = str(mode).strip().upper()
        if mode_s not in WATCH_MODES:
            raise FileMonitoringError(
                f"watch_mode must be one of {list(WATCH_MODES)}",
                status_code=400,
            )
        if mode_s in {"AGENT", "AGENTLESS_POLL"}:
            if not live_allowed(
                tenant_id=tid, capability="file_watch_live", settings=cfg
            ):
                raise FileMonitoringError(
                    "Live file watching is disabled (platform and/or tenant gate).",
                    status_code=403,
                )
            updates["execution_mode"] = "LIVE"
        else:
            updates["execution_mode"] = "SIMULATED"
            updates["agent_id"] = None
            updates["os_watcher"] = None
            updates["poll_url"] = None
            updates["last_polled_at"] = None
        updates["watch_mode"] = mode_s

    if "agent_id" in payload and payload["agent_id"] is not None:
        aid = str(payload["agent_id"]).strip() or None
        updates["agent_id"] = aid
    if "os_watcher" in payload and payload["os_watcher"] is not None:
        watcher = str(payload["os_watcher"]).strip().lower()
        if watcher and watcher not in OS_WATCHERS:
            raise FileMonitoringError(
                f"os_watcher must be one of {sorted(OS_WATCHERS)}",
                status_code=400,
            )
        updates["os_watcher"] = watcher or None
    if "status" in payload and payload["status"] is not None:
        status = str(payload["status"]).strip().lower()
        if status not in {"active", "paused", "error"}:
            raise FileMonitoringError("invalid status", status_code=400)
        updates["status"] = status
    if "label" in payload and payload["label"] is not None:
        updates["label"] = str(payload["label"]).strip()[:128]
    if "notes" in payload and payload["notes"] is not None:
        updates["notes"] = str(payload["notes"]).strip()[:512]

    if "poll_url" in payload:
        url = payload["poll_url"]
        updates["poll_url"] = str(url).strip()[:2048] if url else None
    if "poll_interval_seconds" in payload and payload["poll_interval_seconds"] is not None:
        try:
            interval = int(payload["poll_interval_seconds"])
        except (TypeError, ValueError) as exc:
            raise FileMonitoringError(
                "poll_interval_seconds must be an integer", status_code=400
            ) from exc
        if interval < MIN_POLL_INTERVAL or interval > MAX_POLL_INTERVAL:
            raise FileMonitoringError(
                f"poll_interval_seconds must be {MIN_POLL_INTERVAL}–{MAX_POLL_INTERVAL}",
                status_code=400,
            )
        updates["poll_interval_seconds"] = interval
    if "poll_method" in payload and payload["poll_method"] is not None:
        method = str(payload["poll_method"]).strip().upper()
        if method not in {"GET", "HEAD"}:
            raise FileMonitoringError(
                "poll_method must be GET or HEAD", status_code=400
            )
        updates["poll_method"] = method
    if "egress_allowlist" in payload:
        raw = payload["egress_allowlist"]
        if raw is None:
            updates["egress_allowlist"] = None
        elif isinstance(raw, list):
            updates["egress_allowlist"] = [
                str(x).strip() for x in raw if str(x).strip()
            ]
        else:
            raise FileMonitoringError(
                "egress_allowlist must be a list of hosts/CIDRs", status_code=400
            )

    effective_mode = updates.get("watch_mode") or existing.get("watch_mode") or "SIMULATED"
    if effective_mode == "AGENT":
        aid = updates.get("agent_id", existing.get("agent_id"))
        if not aid:
            raise FileMonitoringError(
                "AGENT watch_mode requires agent_id", status_code=400
            )
        # Default OS watcher when unset.
        if not updates.get("os_watcher") and not existing.get("os_watcher"):
            updates["os_watcher"] = "inotify"
        # Mirror into agent desired_watch_ids when possible.
        try:
            from . import agents as agents_service

            agent = agents_service.get_agent(tenant_id=tid, agent_id=str(aid))
            if agent:
                desired = list(agent.get("desired_watch_ids") or [])
                if wid not in desired:
                    desired.append(wid)
                    agents_service.patch_agent_fields(
                        tenant_id=tid,
                        agent_id=str(aid),
                        fields={"desired_watch_ids": desired},
                    )
        except Exception:  # noqa: BLE001 — desired-state sync is best-effort
            pass
    if effective_mode == "AGENTLESS_POLL":
        poll_url = updates.get("poll_url", existing.get("poll_url"))
        if not poll_url:
            raise FileMonitoringError(
                "AGENTLESS_POLL requires poll_url (HTTP ETag/checksum path)",
                status_code=400,
            )
        if "poll_interval_seconds" not in updates and not existing.get(
            "poll_interval_seconds"
        ):
            updates["poll_interval_seconds"] = DEFAULT_POLL_INTERVAL
        if "poll_method" not in updates and not existing.get("poll_method"):
            updates["poll_method"] = "HEAD"

    result = _targets().find_one_and_update(
        merge_tenant_filter({"watch_id": wid}, tid),
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    return serialize_document(result)


def default_http_checksum_fetch(
    *,
    url: str,
    method: str = "HEAD",
    timeout_seconds: float = 5.0,
    platform_allowlist: str = "",
    check_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    """Limited agentless path: HTTP ETag / body sha256 + Content-Length."""
    hostname = host_from_endpoint(url=url)
    assert_egress_allowed(
        hostname=hostname,
        platform_allowlist=platform_allowlist,
        check_allowlist=check_allowlist,
    )
    req = Request(url, method=(method or "HEAD").upper())
    with urlopen(req, timeout=max(0.1, float(timeout_seconds))) as resp:
        etag = (resp.headers.get("ETag") or "").strip().strip('"')
        length = resp.headers.get("Content-Length")
        body = b""
        if (method or "HEAD").upper() == "GET":
            body = resp.read(1_048_576)
        size_bytes = None
        if length is not None:
            try:
                size_bytes = int(length)
            except ValueError:
                size_bytes = len(body) if body else None
        elif body:
            size_bytes = len(body)
        if etag:
            content_hash = f"etag:{etag}"
        elif body:
            content_hash = f"sha256:{hashlib.sha256(body).hexdigest()}"
        else:
            last_mod = (resp.headers.get("Last-Modified") or "").strip()
            if last_mod:
                content_hash = f"last-modified:{last_mod}"
            else:
                content_hash = f"http-status:{getattr(resp, 'status', resp.getcode())}"
        return {
            "ok": True,
            "content_hash": content_hash,
            "size_bytes": size_bytes,
            "message": "checksum ok",
            "denied": False,
        }


def fetch_checksum(
    *,
    url: str,
    method: str = "HEAD",
    timeout_seconds: float = 5.0,
    platform_allowlist: str = "",
    check_allowlist: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve checksum via test double or default HTTP fetcher."""
    fetcher = _checksum_fetcher or default_http_checksum_fetch
    try:
        return fetcher(
            url=url,
            method=method,
            timeout_seconds=timeout_seconds,
            platform_allowlist=platform_allowlist,
            check_allowlist=check_allowlist,
        )
    except EgressDenied as exc:
        return {
            "ok": False,
            "content_hash": None,
            "size_bytes": None,
            "message": exc.message,
            "denied": True,
        }
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {
            "ok": False,
            "content_hash": None,
            "size_bytes": None,
            "message": f"poll failed: {exc}",
            "denied": False,
        }


def poll_watch_once(
    *,
    tenant_id: str,
    watch_id: str,
    settings: Settings | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run one AGENTLESS_POLL checksum check; write LIVE event on change."""
    tid = require_tenant_id(tenant_id)
    cfg = settings or get_settings()
    if not live_allowed(tenant_id=tid, capability="file_watch_live", settings=cfg):
        raise FileMonitoringError(
            "Live file watching is disabled (platform and/or tenant gate).",
            status_code=403,
        )
    # Agentless path also needs agentless gate.
    if not live_allowed(tenant_id=tid, capability="agentless_poll", settings=cfg):
        raise FileMonitoringError(
            "Agentless poll gate is off for this tenant.",
            status_code=403,
        )

    wid = watch_id.strip()
    target = _targets().find_one(merge_tenant_filter({"watch_id": wid}, tid))
    if target is None:
        raise FileMonitoringError(f"Watch target '{wid}' not found", status_code=404)
    if str(target.get("watch_mode") or "") != "AGENTLESS_POLL":
        raise FileMonitoringError(
            "poll-once requires watch_mode=AGENTLESS_POLL", status_code=400
        )
    if str(target.get("status") or "") == "paused" and not force:
        return {
            "ok": True,
            "skipped": True,
            "reason": "paused",
            "watch_id": wid,
            "changed": False,
        }

    poll_url = str(target.get("poll_url") or "").strip()
    if not poll_url:
        raise FileMonitoringError("poll_url is required", status_code=400)

    result = fetch_checksum(
        url=poll_url,
        method=str(target.get("poll_method") or "HEAD"),
        timeout_seconds=5.0,
        platform_allowlist=cfg.monitor_egress_allowlist or "",
        check_allowlist=list(target.get("egress_allowlist") or []) or None,
    )
    now = _now()
    if not result.get("ok"):
        _targets().update_one(
            merge_tenant_filter({"watch_id": wid}, tid),
            {
                "$set": {
                    "status": "error" if not result.get("denied") else target.get("status"),
                    "last_polled_at": now,
                    "updated_at": now,
                    "live_status_reason": result.get("message"),
                }
            },
        )
        return {
            "ok": False,
            "watch_id": wid,
            "changed": False,
            "denied": bool(result.get("denied")),
            "message": result.get("message"),
            "execution_mode": "LIVE",
            "data_source": "AGENTLESS_FILE_POLL",
        }

    content_hash = result.get("content_hash")
    size_bytes = result.get("size_bytes")
    prev_hash = target.get("last_content_hash")
    changed = prev_hash is not None and content_hash != prev_hash
    # First successful poll baselines without inventing a "modified" event.
    first_baseline = prev_hash is None
    event_doc = None
    version = int(target.get("latest_version") or 0)
    if changed or (first_baseline and force):
        version = version + 1
        event_doc = stamp_tenant_id(
            {
                "event_id": _new_event_id(),
                "watch_id": wid,
                "path": target.get("path"),
                "version": version,
                "change_kind": "created" if first_baseline else "modified",
                "actor": "monitor-agentless-poll",
                "actor_type": "system",
                "changed_at": now,
                "summary": (
                    "AGENTLESS_POLL baseline checksum"
                    if first_baseline
                    else f"AGENTLESS_POLL checksum change ({prev_hash} → {content_hash})"
                ),
                "content_hash": content_hash,
                "size_bytes": size_bytes,
                "execution_mode": "LIVE",
                "data_source": "AGENTLESS_FILE_POLL",
                "note": "LIVE agentless HTTP checksum poll",
                "created_at": now,
            },
            tenant_id=tid,
        )
        _events().insert_one(event_doc)

    set_fields: dict[str, Any] = {
        "last_content_hash": content_hash,
        "last_size_bytes": size_bytes,
        "last_polled_at": now,
        "updated_at": now,
        "execution_mode": "LIVE",
        "watch_mode": "AGENTLESS_POLL",
        "status": "active",
        "live_status_reason": None,
    }
    if event_doc is not None:
        set_fields["latest_version"] = version
        set_fields["latest_actor"] = "monitor-agentless-poll"
        set_fields["latest_changed_at"] = now
    _targets().update_one(
        merge_tenant_filter({"watch_id": wid}, tid),
        {"$set": set_fields},
    )
    return {
        "ok": True,
        "watch_id": wid,
        "changed": bool(event_doc) and not first_baseline,
        "baselined": bool(event_doc) and first_baseline,
        "content_hash": content_hash,
        "size_bytes": size_bytes,
        "version": version if event_doc else int(target.get("latest_version") or 0),
        "event": serialize_document(event_doc) if event_doc else None,
        "execution_mode": "LIVE",
        "data_source": "AGENTLESS_FILE_POLL",
        "live_probes": True,
    }


def run_due_file_polls_for_tenant(
    *,
    tenant_id: str,
    settings: Settings | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Poll due AGENTLESS_POLL watches for a tenant (poller hook)."""
    tid = require_tenant_id(tenant_id)
    cfg = settings or get_settings()
    if not live_allowed(tenant_id=tid, capability="file_watch_live", settings=cfg):
        return {
            "tenant_id": tid,
            "skipped": True,
            "reason": "file_watch_live_gate_off",
            "ran": 0,
            "results": [],
        }
    if not live_allowed(tenant_id=tid, capability="agentless_poll", settings=cfg):
        return {
            "tenant_id": tid,
            "skipped": True,
            "reason": "agentless_poll_gate_off",
            "ran": 0,
            "results": [],
        }

    now = _now()
    cursor = _targets().find(
        merge_tenant_filter(
            {
                "watch_mode": "AGENTLESS_POLL",
                "status": {"$ne": "paused"},
                "poll_url": {"$exists": True, "$nin": [None, ""]},
            },
            tid,
        )
    ).limit(max(1, int(limit)))

    results: list[dict[str, Any]] = []
    ran = 0
    for doc in cursor:
        interval = int(doc.get("poll_interval_seconds") or DEFAULT_POLL_INTERVAL)
        last = doc.get("last_polled_at")
        if last is not None:
            if getattr(last, "tzinfo", None) is None:
                last = last.replace(tzinfo=timezone.utc)
            if (now - last).total_seconds() < interval:
                continue
        try:
            outcome = poll_watch_once(
                tenant_id=tid,
                watch_id=str(doc.get("watch_id")),
                settings=cfg,
                force=False,
            )
        except FileMonitoringError as exc:
            outcome = {
                "ok": False,
                "watch_id": doc.get("watch_id"),
                "message": exc.message,
            }
        results.append(outcome)
        ran += 1
    return {
        "tenant_id": tid,
        "skipped": False,
        "ran": ran,
        "results": results,
    }
