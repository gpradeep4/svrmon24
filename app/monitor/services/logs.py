"""SIMULATED log streams + searchable events (tenant-scoped, monitor DB).

No real syslog/HTTP ingest. Demo events are written only via admin
``simulate-tick``. Retention is enforced via ``log_events_retained``
entitlements (trim oldest after inserts).
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from ...serialization import serialize_document
from ...services import entitlements as entitlements_service
from ...services.entitlements import EntitlementError
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id, tenant_filter
from .indexes import ensure_monitor_indexes
from .meta import DATA_SOURCE, EXECUTION_MODE

STREAMS_COLLECTION = "log_streams"
EVENTS_COLLECTION = "log_events"
TICKS_COLLECTION = "monitor_simulate_ticks"

SEVERITIES: tuple[str, ...] = (
    "debug",
    "info",
    "warning",
    "error",
    "critical",
)
SOURCES: tuple[str, ...] = ("agentless", "agent", "simulated")
SOURCE_KINDS: tuple[str, ...] = (
    "application",
    "system",
    "security",
    "access",
    "database",
    "network",
    "other",
)
STREAM_STATUSES: tuple[str, ...] = ("active", "paused", "error")

_DEMO_MESSAGES: tuple[tuple[str, str], ...] = (
    ("info", "Request completed successfully status=200 latency_ms={n}"),
    ("info", "Heartbeat OK collect_mode={mode} probe=synthetic"),
    ("debug", "Cache lookup key=user:{n} hit=true"),
    ("warning", "Elevated latency detected p95={n}ms threshold=250"),
    ("warning", "Disk usage approaching limit mount=/var used_pct={n}"),
    ("error", "Upstream timeout connecting to dependency retry={n}"),
    ("error", "Authentication failure for principal=svc-{n}"),
    ("critical", "Health check failed — marking target degraded"),
    ("info", "Rotated SIMULATED log segment sequence={n}"),
    ("debug", "Metric scrape tick sample_count={n}"),
)


class MonitorLogsError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_stream_id() -> str:
    return f"ls-{uuid.uuid4().hex[:12]}"


def _new_event_id() -> str:
    return f"le-{uuid.uuid4().hex[:12]}"


def _streams() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[STREAMS_COLLECTION]


def _events() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[EVENTS_COLLECTION]


def _ticks() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[TICKS_COLLECTION]


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    return serialize_document(doc)


def count_log_events(*, tenant_id: str) -> int:
    tid = require_tenant_id(tenant_id)
    return int(_events().count_documents(tenant_filter(tid)))


def count_log_streams(*, tenant_id: str) -> int:
    tid = require_tenant_id(tenant_id)
    return int(_streams().count_documents(tenant_filter(tid)))


def enforce_log_events_retention(*, tenant_id: str) -> int:
    """Trim oldest events when over ``log_events_retained``. Returns trimmed count."""
    tid = require_tenant_id(tenant_id)
    limit = entitlements_service.log_events_retained_limit(tid)
    if limit is None:
        return 0
    coll = _events()
    total = coll.count_documents(tenant_filter(tid))
    if total <= limit:
        return 0
    excess = total - limit
    oldest = list(
        coll.find(tenant_filter(tid), {"_id": 1})
        .sort([("observed_at", ASCENDING), ("_id", ASCENDING)])
        .limit(excess)
    )
    if not oldest:
        return 0
    ids = [row["_id"] for row in oldest]
    result = coll.delete_many({"_id": {"$in": ids}})
    return int(result.deleted_count)


def _day_key(when: datetime | None = None) -> str:
    stamp = when or _now()
    return stamp.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _ticks_today(*, tenant_id: str) -> int:
    tid = require_tenant_id(tenant_id)
    doc = _ticks().find_one({"tenant_id": tid, "day": _day_key()})
    if not doc:
        return 0
    return int(doc.get("count") or 0)


def _assert_can_simulate_tick(*, tenant_id: str) -> None:
    tid = require_tenant_id(tenant_id)
    limit = entitlements_service.monitor_simulate_ticks_per_day_limit(tid)
    if limit is None:
        return
    used = _ticks_today(tenant_id=tid)
    if used >= limit:
        raise EntitlementError(
            f"Plan limit reached for monitor_simulate_ticks_per_day "
            f"({used}/{limit})."
        )


def _record_tick(*, tenant_id: str) -> int:
    tid = require_tenant_id(tenant_id)
    day = _day_key()
    now = _now()
    _ticks().update_one(
        {"tenant_id": tid, "day": day},
        {
            "$inc": {"count": 1},
            "$set": {"updated_at": now},
            "$setOnInsert": {
                "tenant_id": tid,
                "day": day,
                "created_at": now,
            },
        },
        upsert=True,
    )
    return _ticks_today(tenant_id=tid)


def _stable_collect_mode(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return "AGENT" if int(digest[:2], 16) % 2 else "AGENTLESS"


def _source_for_mode(collect_mode: str, *, force_simulated: bool = False) -> str:
    if force_simulated:
        return "simulated"
    mode = (collect_mode or "AGENTLESS").upper()
    if mode == "AGENT":
        return "agent"
    return "agentless"


def ensure_default_streams(*, tenant_id: str) -> list[dict[str, Any]]:
    """Create a small set of SIMULATED streams linked to monitor targets when possible."""
    tid = require_tenant_id(tenant_id)
    coll = _streams()
    existing = list(coll.find(tenant_filter(tid)).sort([("name", ASCENDING)]))
    if existing:
        return [_serialize(doc) for doc in existing]  # type: ignore[misc]

    from ...db import require_monitor_database

    targets = list(
        require_monitor_database()["monitor_targets"]
        .find(tenant_filter(tid))
        .sort([("domain", ASCENDING), ("name_snapshot", ASCENDING)])
        .limit(6)
    )
    now = _now()
    created: list[dict[str, Any]] = []
    if targets:
        for target in targets:
            cid = str(target.get("component_id") or "")
            name = str(target.get("name_snapshot") or cid or "target")
            domain = str(target.get("domain") or "application")
            kind_map = {
                "server": "system",
                "network": "network",
                "application": "application",
                "database": "database",
                "middleware": "application",
            }
            mode = str(target.get("collect_mode") or _stable_collect_mode(cid)).upper()
            if mode not in {"AGENTLESS", "AGENT"}:
                mode = "AGENTLESS"
            doc = stamp_tenant_id(
                {
                    "stream_id": _new_stream_id(),
                    "name": f"{name} · {domain} logs",
                    "component_id": cid or None,
                    "target_id": target.get("target_id"),
                    "source_kind": kind_map.get(domain, "other"),
                    "status": "active",
                    "collect_mode": mode,
                    "execution_mode": EXECUTION_MODE,
                    "data_source": DATA_SOURCE,
                    "created_at": now,
                    "updated_at": now,
                },
                tenant_id=tid,
            )
            coll.insert_one(doc)
            created.append(doc)
    else:
        # Fallback demo streams when no targets synced yet.
        for idx, (name, kind, mode) in enumerate(
            (
                ("Demo app access", "access", "AGENTLESS"),
                ("Demo system journal", "system", "AGENT"),
                ("Demo security audit", "security", "AGENTLESS"),
            )
        ):
            doc = stamp_tenant_id(
                {
                    "stream_id": _new_stream_id(),
                    "name": name,
                    "component_id": None,
                    "target_id": None,
                    "source_kind": kind,
                    "status": "active",
                    "collect_mode": mode,
                    "execution_mode": EXECUTION_MODE,
                    "data_source": DATA_SOURCE,
                    "created_at": now + timedelta(milliseconds=idx),
                    "updated_at": now + timedelta(milliseconds=idx),
                },
                tenant_id=tid,
            )
            coll.insert_one(doc)
            created.append(doc)
    return [_serialize(doc) for doc in created]  # type: ignore[misc]


def list_streams(
    *,
    tenant_id: str,
    q: str | None = None,
    component_id: str | None = None,
    source_kind: str | None = None,
    status: str | None = None,
    collect_mode: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    ensure_default_streams(tenant_id=tid)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    query: dict[str, Any] = {}
    if component_id:
        query["component_id"] = component_id.strip()
    if source_kind:
        sk = source_kind.strip().lower()
        if sk not in SOURCE_KINDS:
            raise MonitorLogsError(
                f"Invalid source_kind '{source_kind}' "
                f"(expected one of: {', '.join(SOURCE_KINDS)})",
                status_code=422,
            )
        query["source_kind"] = sk
    if status:
        st = status.strip().lower()
        if st not in STREAM_STATUSES:
            raise MonitorLogsError(
                f"Invalid status '{status}' "
                f"(expected one of: {', '.join(STREAM_STATUSES)})",
                status_code=422,
            )
        query["status"] = st
    if collect_mode:
        mode = collect_mode.strip().upper()
        if mode not in {"AGENTLESS", "AGENT"}:
            raise MonitorLogsError(
                "Invalid collect_mode (expected AGENTLESS or AGENT)",
                status_code=422,
            )
        query["collect_mode"] = mode
    if q:
        term = q.strip()
        if term:
            query["$or"] = [
                {"name": {"$regex": term, "$options": "i"}},
                {"stream_id": {"$regex": term, "$options": "i"}},
                {"component_id": {"$regex": term, "$options": "i"}},
            ]
    filt = merge_tenant_filter(query, tid)
    coll = _streams()
    total = coll.count_documents(filt)
    cursor = (
        coll.find(filt)
        .sort([("name", ASCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [_serialize(doc) for doc in cursor]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "items": items,
        "tenant_id": tid,
        "execution_mode": EXECUTION_MODE,
        "live_probes": False,
    }


def list_events(
    *,
    tenant_id: str,
    q: str | None = None,
    severity: str | None = None,
    stream_id: str | None = None,
    component_id: str | None = None,
    source: str | None = None,
    collect_mode: str | None = None,
    page: int = 1,
    page_size: int = 50,
    sort_dir: str = "desc",
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    direction = DESCENDING if sort_dir.lower() != "asc" else ASCENDING
    query: dict[str, Any] = {}
    if stream_id:
        query["stream_id"] = stream_id.strip()
    if component_id:
        query["component_id"] = component_id.strip()
    if severity:
        # Allow comma-separated severities.
        parts = [p.strip().lower() for p in severity.split(",") if p.strip()]
        bad = [p for p in parts if p not in SEVERITIES]
        if bad:
            raise MonitorLogsError(
                f"Invalid severity '{severity}' "
                f"(expected one of: {', '.join(SEVERITIES)})",
                status_code=422,
            )
        if len(parts) == 1:
            query["severity"] = parts[0]
        elif parts:
            query["severity"] = {"$in": parts}
    if source:
        src = source.strip().lower()
        if src not in SOURCES:
            raise MonitorLogsError(
                f"Invalid source '{source}' "
                f"(expected one of: {', '.join(SOURCES)})",
                status_code=422,
            )
        query["source"] = src
    if collect_mode:
        mode = collect_mode.strip().upper()
        if mode not in {"AGENTLESS", "AGENT"}:
            raise MonitorLogsError(
                "Invalid collect_mode (expected AGENTLESS or AGENT)",
                status_code=422,
            )
        query["collect_mode"] = mode
    if q:
        term = q.strip()
        if term:
            query["$or"] = [
                {"message": {"$regex": term, "$options": "i"}},
                {"event_id": {"$regex": term, "$options": "i"}},
                {"stream_id": {"$regex": term, "$options": "i"}},
                {"component_id": {"$regex": term, "$options": "i"}},
            ]
    filt = merge_tenant_filter(query, tid)
    coll = _events()
    total = coll.count_documents(filt)
    cursor = (
        coll.find(filt)
        .sort([("observed_at", direction), ("event_id", direction)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [_serialize(doc) for doc in cursor]
    retention_limit = entitlements_service.log_events_retained_limit(tid)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "items": items,
        "tenant_id": tid,
        "execution_mode": EXECUTION_MODE,
        "live_probes": False,
        "data_source": DATA_SOURCE,
        "retained_total": count_log_events(tenant_id=tid),
        "retention_limit": retention_limit,
        "filters": {
            "q": q,
            "severity": severity,
            "stream_id": stream_id,
            "component_id": component_id,
            "source": source,
            "collect_mode": collect_mode,
        },
    }


def simulate_tick(
    *,
    tenant_id: str,
    events_per_stream: int = 3,
) -> dict[str, Any]:
    """Admin-only demo writer: ensure streams and append SIMULATED events."""
    tid = require_tenant_id(tenant_id)
    _assert_can_simulate_tick(tenant_id=tid)

    per = max(1, min(int(events_per_stream or 3), 20))
    streams = ensure_default_streams(tenant_id=tid)
    now = _now()
    coll = _events()
    created = 0
    rng = random.Random(f"{tid}:{_day_key()}:{_ticks_today(tenant_id=tid)}")

    for stream in streams:
        if not stream:
            continue
        stream_id = stream["stream_id"]
        mode = str(stream.get("collect_mode") or "AGENTLESS").upper()
        if mode not in {"AGENTLESS", "AGENT"}:
            mode = "AGENTLESS"
        for i in range(per):
            sev, template = _DEMO_MESSAGES[rng.randrange(len(_DEMO_MESSAGES))]
            # Mix source tags: mostly collect-path, occasional explicit simulated.
            source = _source_for_mode(mode, force_simulated=(i == per - 1))
            n = rng.randint(1, 999)
            message = template.format(n=n, mode=mode.lower())
            observed = now - timedelta(seconds=rng.randint(0, 120) + i)
            doc = stamp_tenant_id(
                {
                    "event_id": _new_event_id(),
                    "stream_id": stream_id,
                    "component_id": stream.get("component_id"),
                    "target_id": stream.get("target_id"),
                    "severity": sev,
                    "message": message,
                    "attrs": {
                        "demo": True,
                        "tick": True,
                        "source_kind": stream.get("source_kind"),
                    },
                    "observed_at": observed,
                    "data_source": DATA_SOURCE,
                    "execution_mode": EXECUTION_MODE,
                    "collect_mode": mode,
                    "source": source,
                    "created_at": now,
                },
                tenant_id=tid,
            )
            coll.insert_one(doc)
            created += 1

    trimmed = enforce_log_events_retention(tenant_id=tid)
    ticks_today = _record_tick(tenant_id=tid)
    retention_limit = entitlements_service.log_events_retained_limit(tid)
    ticks_limit = entitlements_service.monitor_simulate_ticks_per_day_limit(tid)

    # M6: evaluate SIMULATED alert rules after demo telemetry lands.
    from . import alerts as alerts_service

    alert_eval = alerts_service.evaluate_rules(tenant_id=tid)
    return {
        "tenant_id": tid,
        "streams_ensured": len(streams),
        "events_created": created,
        "events_trimmed": trimmed,
        "retained_total": count_log_events(tenant_id=tid),
        "retention_limit": retention_limit,
        "ticks_today": ticks_today,
        "ticks_limit": ticks_limit,
        "execution_mode": EXECUTION_MODE,
        "live_probes": False,
        "data_source": DATA_SOURCE,
        "sources": list(SOURCES),
        "alerts_created": alert_eval.get("created", 0),
        "alerts_open": alert_eval.get("open_count", 0),
        "alert_rules_evaluated": alert_eval.get("rules_evaluated", 0),
    }

