"""Live HTTP log ingest + ingest keys + syslog source maps (fail-closed).

Writes ``log_events`` with ``execution_mode=LIVE`` only when live gates allow.
Ingest keys store ``key_hash`` only (pepper from env ref). Syslog bind is
optional and handled by ``syslog_receiver``.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, ReturnDocument
from pymongo.collection import Collection

from ...config import Settings, get_settings
from ...serialization import serialize_document
from ...services import entitlements as entitlements_service
from ...services.entitlements import EntitlementError
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id, tenant_filter
from .indexes import ensure_monitor_indexes
from .live_gates import live_allowed
from .logs import (
    EVENTS_COLLECTION,
    SEVERITIES,
    STREAMS_COLLECTION,
    MonitorLogsError,
    _new_event_id,
    count_log_events,
    enforce_log_events_retention,
    ensure_default_streams,
)

KEYS_COLLECTION = "log_ingest_keys"
SYSLOG_SOURCES_COLLECTION = "syslog_sources"
INGEST_DAILY_COLLECTION = "monitor_log_ingest_daily"

DEFAULT_MAX_EVENTS = 100
DEFAULT_MAX_BODY_BYTES = 1_048_576
DEFAULT_DEV_PEPPER = "svrmon24-dev-ingest-pepper"
TOKEN_PREFIX = "mik_"


class MonitorIngestError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_key(when: datetime | None = None) -> str:
    stamp = when or _now()
    return stamp.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _keys() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[KEYS_COLLECTION]


def _syslog_sources() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[SYSLOG_SOURCES_COLLECTION]


def _ingest_daily() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[INGEST_DAILY_COLLECTION]


def _streams() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[STREAMS_COLLECTION]


def _events() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[EVENTS_COLLECTION]


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    return serialize_document(doc)


def resolve_ingest_pepper(settings: Settings | None = None) -> str:
    """Pepper for hashing ingest keys — never stored in Mongo."""
    cfg = settings or get_settings()
    ref = (cfg.monitor_agent_token_pepper_env_ref or "MONITOR_AGENT_TOKEN_PEPPER").strip()
    value = os.getenv(ref, "").strip()
    if value:
        return value
    # Lab/test fallback — production should set the env ref.
    return DEFAULT_DEV_PEPPER


def hash_ingest_token(token: str, *, pepper: str | None = None) -> str:
    pep = pepper if pepper is not None else resolve_ingest_pepper()
    return hashlib.sha256(f"{pep}:{token}".encode("utf-8")).hexdigest()


def _new_key_id() -> str:
    return f"lik-{uuid.uuid4().hex[:12]}"


def _new_source_id() -> str:
    return f"sys-{uuid.uuid4().hex[:12]}"


def _generate_token() -> str:
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def ingest_today_count(*, tenant_id: str) -> int:
    tid = require_tenant_id(tenant_id)
    doc = _ingest_daily().find_one({"tenant_id": tid, "day": _day_key()})
    if not doc:
        return 0
    return int(doc.get("count") or 0)


def _record_ingest(*, tenant_id: str, count: int) -> int:
    tid = require_tenant_id(tenant_id)
    if count <= 0:
        return ingest_today_count(tenant_id=tid)
    day = _day_key()
    now = _now()
    _ingest_daily().update_one(
        {"tenant_id": tid, "day": day},
        {
            "$inc": {"count": int(count)},
            "$set": {"updated_at": now},
            "$setOnInsert": {
                "tenant_id": tid,
                "day": day,
                "created_at": now,
            },
        },
        upsert=True,
    )
    return ingest_today_count(tenant_id=tid)


def assert_can_ingest_events(*, tenant_id: str, count: int) -> None:
    """Enforce ``monitor_log_ingest_events_per_day`` before accepting a batch."""
    tid = require_tenant_id(tenant_id)
    if count <= 0:
        return
    limit = entitlements_service.monitor_log_ingest_events_per_day_limit(tid)
    if limit is None:
        return
    used = ingest_today_count(tenant_id=tid)
    if used + count > limit:
        raise EntitlementError(
            f"Plan limit reached for monitor_log_ingest_events_per_day "
            f"({used}/{limit}; requested {count})."
        )


def _get_stream(*, tenant_id: str, stream_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    sid = (stream_id or "").strip()
    if not sid:
        return None
    return _streams().find_one(merge_tenant_filter({"stream_id": sid}, tid))


def create_ingest_key(
    *,
    tenant_id: str,
    name: str,
    stream_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Create an active ingest key; plaintext token returned once."""
    tid = require_tenant_id(tenant_id)
    label = (name or "").strip()
    if not label:
        raise MonitorIngestError("name is required", status_code=422)
    sid = (stream_id or "").strip() or None
    if sid and not _get_stream(tenant_id=tid, stream_id=sid):
        raise MonitorIngestError(f"stream_id '{sid}' not found", status_code=404)

    token = _generate_token()
    pepper = resolve_ingest_pepper(settings)
    now = _now()
    key_id = _new_key_id()
    doc = stamp_tenant_id(
        {
            "key_id": key_id,
            "name": label,
            "stream_id": sid,
            "key_hash": hash_ingest_token(token, pepper=pepper),
            "status": "active",
            "created_at": now,
            "revoked_at": None,
            "last_used_at": None,
        },
        tenant_id=tid,
    )
    _keys().insert_one(doc)
    out = _serialize(doc) or {}
    out.pop("key_hash", None)
    out["token"] = token
    return out


def list_ingest_keys(*, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    cursor = _keys().find(tenant_filter(tid)).sort([("created_at", ASCENDING)])
    items = []
    for doc in cursor:
        row = _serialize(doc) or {}
        row.pop("key_hash", None)
        items.append(row)
    return {"total": len(items), "items": items, "tenant_id": tid}


def revoke_ingest_key(*, tenant_id: str, key_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    kid = (key_id or "").strip()
    now = _now()
    result = _keys().find_one_and_update(
        merge_tenant_filter({"key_id": kid}, tid),
        {"$set": {"status": "revoked", "revoked_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise MonitorIngestError(f"ingest key '{kid}' not found", status_code=404)
    out = _serialize(result) or {}
    out.pop("key_hash", None)
    return out


def resolve_ingest_key(
    token: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Resolve an active ingest key by plaintext token. Raises on miss/revoke."""
    raw = (token or "").strip()
    if not raw:
        raise MonitorIngestError("ingest key required", status_code=401)
    pepper = resolve_ingest_pepper(settings)
    digest = hash_ingest_token(raw, pepper=pepper)
    doc = _keys().find_one({"key_hash": digest, "status": "active"})
    if not doc:
        raise MonitorIngestError("invalid or revoked ingest key", status_code=401)
    tid = str(doc.get("tenant_id") or "")
    if not tid:
        raise MonitorIngestError("ingest key missing tenant", status_code=401)
    _keys().update_one(
        {"_id": doc["_id"]},
        {"$set": {"last_used_at": _now()}},
    )
    out = _serialize(doc) or {}
    out.pop("key_hash", None)
    return out


def list_syslog_sources(*, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    cursor = (
        _syslog_sources()
        .find(tenant_filter(tid))
        .sort([("source_ip", ASCENDING)])
    )
    items = [_serialize(doc) for doc in cursor]
    return {"total": len(items), "items": items, "tenant_id": tid}


def _normalize_source_ip(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise MonitorIngestError("source_ip is required", status_code=422)
    try:
        # Accept host IP or CIDR; store canonical form.
        if "/" in text:
            return str(ipaddress.ip_network(text, strict=False))
        return str(ipaddress.ip_address(text))
    except ValueError as exc:
        raise MonitorIngestError(
            f"invalid source_ip '{raw}' (expected IP or CIDR)",
            status_code=422,
        ) from exc


def put_syslog_sources(
    *,
    tenant_id: str,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replace all syslog source mappings for the tenant."""
    tid = require_tenant_id(tenant_id)
    ensure_default_streams(tenant_id=tid)
    now = _now()
    prepared: list[dict[str, Any]] = []
    seen_ips: set[str] = set()
    for raw in sources or []:
        if not isinstance(raw, dict):
            raise MonitorIngestError("each source must be an object", status_code=422)
        source_ip = _normalize_source_ip(str(raw.get("source_ip") or ""))
        if source_ip in seen_ips:
            raise MonitorIngestError(
                f"duplicate source_ip '{source_ip}'", status_code=422
            )
        seen_ips.add(source_ip)
        stream_id = str(raw.get("stream_id") or "").strip()
        if not stream_id:
            raise MonitorIngestError("stream_id is required", status_code=422)
        if not _get_stream(tenant_id=tid, stream_id=stream_id):
            raise MonitorIngestError(
                f"stream_id '{stream_id}' not found", status_code=404
            )
        status = str(raw.get("status") or "active").strip().lower()
        if status not in {"active", "quarantine", "disabled"}:
            raise MonitorIngestError(
                "status must be active, quarantine, or disabled",
                status_code=422,
            )
        source_id = str(raw.get("source_id") or "").strip() or _new_source_id()
        label = raw.get("label")
        prepared.append(
            stamp_tenant_id(
                {
                    "source_id": source_id,
                    "source_ip": source_ip,
                    "stream_id": stream_id,
                    "status": status,
                    "label": (str(label).strip() if label else None) or None,
                    "created_at": now,
                    "updated_at": now,
                },
                tenant_id=tid,
            )
        )

    coll = _syslog_sources()
    coll.delete_many(tenant_filter(tid))
    if prepared:
        coll.insert_many(prepared)
    return list_syslog_sources(tenant_id=tid)


def find_syslog_source_for_ip(
    *,
    source_ip: str,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Find first matching active/quarantine mapping across tenants (bind path)."""
    cfg = settings or get_settings()
    try:
        addr = ipaddress.ip_address((source_ip or "").strip())
    except ValueError:
        return None

    for doc in _syslog_sources().find({"status": {"$in": ["active", "quarantine"]}}):
        tid = str(doc.get("tenant_id") or "")
        if not tid:
            continue
        if not live_allowed(
            tenant_id=tid, capability="log_ingest_syslog", settings=cfg
        ):
            continue
        net_raw = str(doc.get("source_ip") or "")
        try:
            if "/" in net_raw:
                network = ipaddress.ip_network(net_raw, strict=False)
                if addr in network:
                    return doc
            else:
                if addr == ipaddress.ip_address(net_raw):
                    return doc
        except ValueError:
            continue
    return None


def ingest_log_events(
    *,
    tenant_id: str,
    events: list[dict[str, Any]],
    default_stream_id: str | None = None,
    data_source: str = "HTTP_INGEST",
    source_tag: str = "agentless",
    settings: Settings | None = None,
    capability: str = "log_ingest_http",
) -> dict[str, Any]:
    """Write LIVE log events when the capability gate is open.

    Callers must already authenticate (session or ingest key). Gate failure
    raises MonitorIngestError 403 (fail-closed).
    """
    tid = require_tenant_id(tenant_id)
    cfg = settings or get_settings()
    if not live_allowed(tenant_id=tid, capability=capability, settings=cfg):  # type: ignore[arg-type]
        raise MonitorIngestError(
            "Live monitoring is disabled (platform and/or tenant gate). "
            "SIMULATED paths remain available.",
            status_code=403,
        )

    ensure_default_streams(tenant_id=tid)
    batch = list(events or [])
    max_events = DEFAULT_MAX_EVENTS
    if len(batch) > max_events:
        raise MonitorIngestError(
            f"batch exceeds max events ({max_events})",
            status_code=413,
        )

    # Empty batch is a no-op success (keeps L0 gate-open smoke green).
    if not batch:
        return {
            "ok": True,
            "execution_mode": "LIVE",
            "data_source": data_source,
            "accepted": 0,
            "rejected": 0,
            "trimmed": 0,
            "tenant_id": tid,
            "stream_ids": [],
            "errors": [],
            "live_probes": True,
            "ingest_today": ingest_today_count(tenant_id=tid),
            "ingest_limit": entitlements_service.monitor_log_ingest_events_per_day_limit(
                tid
            ),
        }

    default_sid = (default_stream_id or "").strip() or None
    if default_sid and not _get_stream(tenant_id=tid, stream_id=default_sid):
        raise MonitorIngestError(
            f"stream_id '{default_sid}' not found", status_code=404
        )

    # Pre-validate + resolve streams before entitlement + write.
    prepared: list[dict[str, Any]] = []
    errors: list[str] = []
    stream_ids: set[str] = set()
    now = _now()

    for idx, raw in enumerate(batch):
        if not isinstance(raw, dict):
            errors.append(f"event[{idx}]: must be an object")
            continue
        message = str(raw.get("message") or "").strip()
        if not message:
            errors.append(f"event[{idx}]: message is required")
            continue
        if len(message) > 8192:
            errors.append(f"event[{idx}]: message too long")
            continue
        severity = str(raw.get("severity") or "info").strip().lower()
        if severity not in SEVERITIES:
            errors.append(f"event[{idx}]: invalid severity '{severity}'")
            continue
        sid = str(raw.get("stream_id") or default_sid or "").strip()
        if not sid:
            errors.append(f"event[{idx}]: stream_id is required")
            continue
        stream = _get_stream(tenant_id=tid, stream_id=sid)
        if not stream:
            errors.append(f"event[{idx}]: stream_id '{sid}' not found")
            continue

        observed = raw.get("observed_at")
        if observed is None:
            observed_at = now
        elif isinstance(observed, datetime):
            observed_at = observed if observed.tzinfo else observed.replace(
                tzinfo=timezone.utc
            )
        else:
            try:
                text = str(observed).strip().replace("Z", "+00:00")
                observed_at = datetime.fromisoformat(text)
                if observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=timezone.utc)
            except ValueError:
                errors.append(f"event[{idx}]: invalid observed_at")
                continue

        mode = str(
            raw.get("collect_mode") or stream.get("collect_mode") or "AGENTLESS"
        ).upper()
        if mode not in {"AGENTLESS", "AGENT"}:
            mode = "AGENTLESS"
        attrs = raw.get("attrs") if isinstance(raw.get("attrs"), dict) else {}
        component_id = raw.get("component_id") or stream.get("component_id")
        target_id = raw.get("target_id") or stream.get("target_id")
        prepared.append(
            stamp_tenant_id(
                {
                    "event_id": _new_event_id(),
                    "stream_id": sid,
                    "component_id": component_id,
                    "target_id": target_id,
                    "severity": severity,
                    "message": message,
                    "attrs": {
                        **attrs,
                        "ingest": True,
                        "data_source": data_source,
                    },
                    "observed_at": observed_at,
                    "data_source": data_source,
                    "execution_mode": "LIVE",
                    "collect_mode": mode,
                    "source": source_tag
                    if source_tag in {"agentless", "agent", "simulated"}
                    else "agentless",
                    "created_at": now,
                },
                tenant_id=tid,
            )
        )
        stream_ids.add(sid)

    rejected = len(errors)
    if not prepared:
        return {
            "ok": False,
            "execution_mode": "LIVE",
            "data_source": data_source,
            "accepted": 0,
            "rejected": rejected,
            "trimmed": 0,
            "tenant_id": tid,
            "stream_ids": [],
            "errors": errors,
            "live_probes": True,
            "ingest_today": ingest_today_count(tenant_id=tid),
            "ingest_limit": entitlements_service.monitor_log_ingest_events_per_day_limit(
                tid
            ),
        }

    try:
        assert_can_ingest_events(tenant_id=tid, count=len(prepared))
    except EntitlementError as exc:
        raise MonitorIngestError(exc.message, status_code=exc.status_code) from exc

    _events().insert_many(prepared)
    trimmed = enforce_log_events_retention(tenant_id=tid)
    today = _record_ingest(tenant_id=tid, count=len(prepared))

    # Mark streams that received LIVE ingest.
    for sid in stream_ids:
        _streams().update_one(
            merge_tenant_filter({"stream_id": sid}, tid),
            {
                "$set": {
                    "execution_mode": "LIVE",
                    "data_source": data_source,
                    "updated_at": now,
                }
            },
        )

    return {
        "ok": True,
        "execution_mode": "LIVE",
        "data_source": data_source,
        "accepted": len(prepared),
        "rejected": rejected,
        "trimmed": trimmed,
        "tenant_id": tid,
        "stream_ids": sorted(stream_ids),
        "errors": errors,
        "live_probes": True,
        "ingest_today": today,
        "ingest_limit": entitlements_service.monitor_log_ingest_events_per_day_limit(
            tid
        ),
        "retained_total": count_log_events(tenant_id=tid),
    }


def ingest_syslog_message(
    *,
    source_ip: str,
    message: str,
    severity: str = "info",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Map a syslog datagram to a stream and write a LIVE event (or drop)."""
    cfg = settings or get_settings()
    mapping = find_syslog_source_for_ip(source_ip=source_ip, settings=cfg)
    if not mapping:
        return {
            "ok": False,
            "dropped": True,
            "reason": "unknown_source",
            "source_ip": source_ip,
        }

    status = str(mapping.get("status") or "active")
    if status == "disabled":
        return {
            "ok": False,
            "dropped": True,
            "reason": "source_disabled",
            "source_ip": source_ip,
        }

    tid = str(mapping["tenant_id"])
    stream_id = str(mapping["stream_id"])
    sev = (severity or "info").lower()
    if sev not in SEVERITIES:
        sev = "info"
    text = (message or "").strip()
    if not text:
        return {"ok": False, "dropped": True, "reason": "empty_message"}

    attrs: dict[str, Any] = {"syslog_source_ip": source_ip}
    if status == "quarantine":
        attrs["quarantine"] = True
        # Mark stream error when quarantining unknown-ish traffic.
        _streams().update_one(
            merge_tenant_filter({"stream_id": stream_id}, tid),
            {"$set": {"status": "error", "updated_at": _now()}},
        )

    try:
        result = ingest_log_events(
            tenant_id=tid,
            events=[
                {
                    "stream_id": stream_id,
                    "severity": sev,
                    "message": text[:8192],
                    "attrs": attrs,
                }
            ],
            data_source="SYSLOG",
            source_tag="agentless",
            settings=cfg,
            capability="log_ingest_syslog",
        )
    except MonitorIngestError as exc:
        return {
            "ok": False,
            "dropped": True,
            "reason": exc.message,
            "status_code": exc.status_code,
            "source_ip": source_ip,
            "tenant_id": tid,
        }
    result["source_ip"] = source_ip
    result["quarantine"] = status == "quarantine"
    return result
