"""Monitor agent registration, tokens, enrollments (L4).

Tokens and enrollment codes are hashed at rest with the pepper from
``MONITOR_AGENT_TOKEN_PEPPER_ENV_REF`` (never store pepper or plaintext in Mongo).
Register / heartbeat / enroll / rotate are fail-closed behind
``agent_register`` live gates. Revoke + list remain available for ops.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
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
from . import mtls as mtls_service

AGENTS_COLLECTION = "monitor_agents"
ENROLLMENTS_COLLECTION = "monitor_agent_enrollments"

DEFAULT_DEV_PEPPER = "svrmon24-dev-agent-pepper"
TOKEN_PREFIX = "mat_"
ENROLL_PREFIX = "menroll_"
DEFAULT_ENROLLMENT_TTL_SECONDS = 30 * 60
OS_FAMILIES = frozenset({"linux", "windows", "macos", "unix"})
PUBLIC_AGENT_FIELDS = (
    "agent_id",
    "name",
    "os_family",
    "os_name",
    "hostname",
    "version",
    "status",
    "mtls_fingerprint",
    "last_seen_at",
    "labels",
    "enrollment_id",
    "created_at",
    "revoked_at",
    "tenant_id",
    "token_rotated_at",
    "desired_watch_ids",
    "desired_stream_ids",
    "desired_target_ids",
    "desired_updated_at",
)


class MonitorAgentsError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _agents() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[AGENTS_COLLECTION]


def _enrollments() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[ENROLLMENTS_COLLECTION]


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    return serialize_document(doc)


def resolve_agent_pepper(settings: Settings | None = None) -> str:
    """Pepper for hashing agent tokens / enrollment codes — never stored in Mongo."""
    cfg = settings or get_settings()
    ref = (cfg.monitor_agent_token_pepper_env_ref or "MONITOR_AGENT_TOKEN_PEPPER").strip()
    value = os.getenv(ref, "").strip()
    if value:
        return value
    return DEFAULT_DEV_PEPPER


def hash_agent_secret(raw: str, *, pepper: str | None = None) -> str:
    pep = pepper if pepper is not None else resolve_agent_pepper()
    return hashlib.sha256(f"{pep}:{raw}".encode("utf-8")).hexdigest()


def _new_agent_id() -> str:
    return f"agt-{uuid.uuid4().hex[:12]}"


def _new_enrollment_id() -> str:
    return f"enr-{uuid.uuid4().hex[:12]}"


def _generate_token() -> str:
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def _generate_enrollment_code() -> str:
    return f"{ENROLL_PREFIX}{secrets.token_urlsafe(24)}"


def _public_agent(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    row = _serialize(doc) or {}
    row.pop("token_hash", None)
    row.pop("_id", None)
    out = {k: row.get(k) for k in PUBLIC_AGENT_FIELDS if k in row}
    # Preserve any extra non-secret fields already serialized.
    for key, val in row.items():
        if key in {"token_hash", "code_hash"}:
            continue
        if key not in out:
            out[key] = val
    return out


def assert_agent_register_allowed(
    *,
    tenant_id: str,
    settings: Settings | None = None,
) -> None:
    if not live_allowed(
        tenant_id=tenant_id, capability="agent_register", settings=settings
    ):
        raise MonitorAgentsError(
            "Live agent registration is disabled (platform and/or tenant gate).",
            status_code=403,
        )


def count_monitor_agents(*, tenant_id: str, active_only: bool = True) -> int:
    tid = require_tenant_id(tenant_id)
    query: dict[str, Any] = {"tenant_id": tid}
    if active_only:
        query["status"] = {"$in": ["pending", "active", "stale"]}
    return int(_agents().count_documents(query))


def assert_can_register_agent(tenant_id: str) -> None:
    """Enforce ``monitor_agents`` entitlement before registering."""
    tid = require_tenant_id(tenant_id)
    limit = entitlements_service.monitor_agents_limit(tid)
    if limit is None:
        return
    total = count_monitor_agents(tenant_id=tid, active_only=True)
    if total >= limit:
        raise EntitlementError(
            f"Agent limit reached for this tenant "
            f"({total}/{limit}). Upgrade entitlements to register more agents.",
            status_code=403,
        )


def create_enrollment(
    *,
    tenant_id: str,
    created_by: str | None = None,
    label: str | None = None,
    ttl_seconds: int | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Create a one-time enrollment code; plaintext returned once."""
    tid = require_tenant_id(tenant_id)
    assert_agent_register_allowed(tenant_id=tid, settings=settings)

    ttl = int(ttl_seconds) if ttl_seconds is not None else DEFAULT_ENROLLMENT_TTL_SECONDS
    if ttl < 60 or ttl > 86_400:
        raise MonitorAgentsError(
            "ttl_seconds must be between 60 and 86400", status_code=422
        )

    code = _generate_enrollment_code()
    pepper = resolve_agent_pepper(settings)
    now = _now()
    enrollment_id = _new_enrollment_id()
    doc = stamp_tenant_id(
        {
            "enrollment_id": enrollment_id,
            "label": (label or "").strip() or None,
            "code_hash": hash_agent_secret(code, pepper=pepper),
            "status": "pending",
            "expires_at": now + timedelta(seconds=ttl),
            "created_by": (created_by or "").strip() or None,
            "created_at": now,
            "consumed_at": None,
            "consumed_by_agent_id": None,
        },
        tenant_id=tid,
    )
    _enrollments().insert_one(doc)
    out = _serialize(doc) or {}
    out.pop("code_hash", None)
    out["code"] = code
    return out


def list_enrollments(*, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _expire_stale_enrollments(tenant_id=tid)
    cursor = (
        _enrollments()
        .find(tenant_filter(tid))
        .sort([("created_at", ASCENDING)])
    )
    items = []
    for doc in cursor:
        row = _serialize(doc) or {}
        row.pop("code_hash", None)
        items.append(row)
    return {"total": len(items), "items": items, "tenant_id": tid}


def _expire_stale_enrollments(*, tenant_id: str) -> None:
    tid = require_tenant_id(tenant_id)
    now = _now()
    _enrollments().update_many(
        merge_tenant_filter(
            {"status": "pending", "expires_at": {"$lte": now}},
            tid,
        ),
        {"$set": {"status": "expired"}},
    )


def _consume_enrollment(
    *,
    enrollment_code: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    raw = (enrollment_code or "").strip()
    if not raw:
        raise MonitorAgentsError("enrollment_code is required", status_code=422)
    pepper = resolve_agent_pepper(settings)
    digest = hash_agent_secret(raw, pepper=pepper)
    now = _now()
    doc = _enrollments().find_one({"code_hash": digest})
    if not doc:
        raise MonitorAgentsError("invalid enrollment code", status_code=401)
    status = str(doc.get("status") or "")
    if status == "consumed":
        raise MonitorAgentsError("enrollment code already used", status_code=409)
    if status == "expired":
        raise MonitorAgentsError("enrollment code expired", status_code=410)
    expires = doc.get("expires_at")
    if isinstance(expires, datetime):
        exp = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
        if exp <= now:
            _enrollments().update_one(
                {"_id": doc["_id"]},
                {"$set": {"status": "expired"}},
            )
            raise MonitorAgentsError("enrollment code expired", status_code=410)
    if status != "pending":
        raise MonitorAgentsError("enrollment code not usable", status_code=401)
    return doc


def register_agent(
    *,
    enrollment_code: str,
    name: str,
    hostname: str | None = None,
    os_family: str = "linux",
    os_name: str | None = None,
    version: str | None = None,
    labels: dict[str, str] | None = None,
    mtls_fingerprint: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Exchange one-time enrollment code → agent_id + bearer token (once)."""
    enrollment = _consume_enrollment(
        enrollment_code=enrollment_code, settings=settings
    )
    tid = require_tenant_id(str(enrollment.get("tenant_id") or ""))
    assert_agent_register_allowed(tenant_id=tid, settings=settings)
    assert_can_register_agent(tid)

    label = (name or "").strip()
    if not label:
        raise MonitorAgentsError("name is required", status_code=422)
    family = str(os_family or "linux").strip().lower()
    if family not in OS_FAMILIES:
        raise MonitorAgentsError(
            f"os_family must be one of: {', '.join(sorted(OS_FAMILIES))}",
            status_code=422,
        )

    token = _generate_token()
    pepper = resolve_agent_pepper(settings)
    now = _now()
    agent_id = _new_agent_id()
    agent_doc = stamp_tenant_id(
        {
            "agent_id": agent_id,
            "name": label,
            "os_family": family,
            "os_name": (os_name or "").strip() or None,
            "hostname": (hostname or "").strip() or None,
            "version": (version or "").strip() or None,
            "status": "active",
            "token_hash": hash_agent_secret(token, pepper=pepper),
            "mtls_fingerprint": (mtls_fingerprint or "").strip() or None,
            "last_seen_at": now,
            "labels": dict(labels or {}),
            "enrollment_id": enrollment.get("enrollment_id"),
            "created_at": now,
            "revoked_at": None,
            "token_rotated_at": None,
        },
        tenant_id=tid,
    )

    # Atomically consume enrollment (single-use).
    consumed = _enrollments().find_one_and_update(
        {
            "_id": enrollment["_id"],
            "status": "pending",
        },
        {
            "$set": {
                "status": "consumed",
                "consumed_at": now,
                "consumed_by_agent_id": agent_id,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if not consumed:
        raise MonitorAgentsError("enrollment code already used", status_code=409)

    _agents().insert_one(agent_doc)
    out = _public_agent(agent_doc) or {}
    out["token"] = token
    return out


def list_agents(
    *,
    tenant_id: str,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    query: dict[str, Any] = {"tenant_id": tid}
    if status:
        query["status"] = str(status).strip().lower()
    total = int(_agents().count_documents(query))
    skip = max(0, (int(page) - 1) * int(page_size))
    cursor = (
        _agents()
        .find(query)
        .sort([("created_at", ASCENDING)])
        .skip(skip)
        .limit(int(page_size))
    )
    items = [_public_agent(doc) for doc in cursor]
    return {
        "total": total,
        "items": items,
        "page": int(page),
        "page_size": int(page_size),
        "tenant_id": tid,
    }


def get_agent(*, tenant_id: str, agent_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    aid = (agent_id or "").strip()
    doc = _agents().find_one(merge_tenant_filter({"agent_id": aid}, tid))
    if not doc:
        raise MonitorAgentsError(f"agent '{aid}' not found", status_code=404)
    return _public_agent(doc) or {}


def resolve_agent_token(
    token: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Resolve an active agent by plaintext bearer token."""
    raw = (token or "").strip()
    if not raw:
        raise MonitorAgentsError("agent token required", status_code=401)
    pepper = resolve_agent_pepper(settings)
    digest = hash_agent_secret(raw, pepper=pepper)
    doc = _agents().find_one({"token_hash": digest})
    if not doc:
        raise MonitorAgentsError("invalid or revoked agent token", status_code=401)
    status = str(doc.get("status") or "")
    if status == "revoked":
        raise MonitorAgentsError("agent revoked", status_code=401)
    if status not in {"active", "pending", "stale"}:
        raise MonitorAgentsError("agent not active", status_code=401)
    tid = str(doc.get("tenant_id") or "")
    if not tid:
        raise MonitorAgentsError("agent missing tenant", status_code=401)
    out = _public_agent(doc) or {}
    return out


def resolve_agent_auth(
    *,
    token: str | None = None,
    headers: Any = None,
    expected_agent_id: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Accept agent bearer token **or** feature-flagged mTLS identity."""
    # Prefer explicit bearer token when present.
    if token and token.strip():
        agent = resolve_agent_token(token, settings=settings)
        if expected_agent_id and agent.get("agent_id") != expected_agent_id:
            raise MonitorAgentsError("agent token does not match path id", status_code=403)
        return {"auth_mode": "token", "agent": agent}

    identity = mtls_service.extract_mtls_identity(headers or {}, settings=settings)
    if identity is None:
        raise MonitorAgentsError(
            "agent token or verified mTLS client cert required",
            status_code=401,
        )
    aid = identity.agent_id
    if expected_agent_id and aid != expected_agent_id:
        raise MonitorAgentsError("mTLS OU does not match path agent id", status_code=403)

    query: dict[str, Any] = {"agent_id": aid, "status": {"$ne": "revoked"}}
    if identity.tenant_id:
        query["tenant_id"] = identity.tenant_id
    doc = _agents().find_one(query)
    if not doc:
        raise MonitorAgentsError("mTLS agent not registered", status_code=401)
    if identity.fingerprint and doc.get("mtls_fingerprint"):
        if identity.fingerprint != doc.get("mtls_fingerprint"):
            raise MonitorAgentsError("mTLS fingerprint mismatch", status_code=401)
    return {"auth_mode": "mtls", "agent": _public_agent(doc) or {}, "mtls": identity}


def heartbeat_agent(
    *,
    agent_id: str,
    tenant_id: str,
    version: str | None = None,
    hostname: str | None = None,
    labels: dict[str, str] | None = None,
    status_note: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    assert_agent_register_allowed(tenant_id=tid, settings=settings)
    aid = (agent_id or "").strip()
    now = _now()
    updates: dict[str, Any] = {
        "last_seen_at": now,
        "status": "active",
    }
    if version is not None and str(version).strip():
        updates["version"] = str(version).strip()
    if hostname is not None and str(hostname).strip():
        updates["hostname"] = str(hostname).strip()
    if labels is not None:
        updates["labels"] = dict(labels)
    if status_note is not None:
        updates["status_note"] = str(status_note).strip() or None

    result = _agents().find_one_and_update(
        merge_tenant_filter(
            {"agent_id": aid, "status": {"$ne": "revoked"}},
            tid,
        ),
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise MonitorAgentsError(f"agent '{aid}' not found or revoked", status_code=404)
    return _public_agent(result) or {}


def rotate_agent_token(
    *,
    tenant_id: str,
    agent_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    assert_agent_register_allowed(tenant_id=tid, settings=settings)
    aid = (agent_id or "").strip()
    token = _generate_token()
    pepper = resolve_agent_pepper(settings)
    now = _now()
    result = _agents().find_one_and_update(
        merge_tenant_filter(
            {"agent_id": aid, "status": {"$ne": "revoked"}},
            tid,
        ),
        {
            "$set": {
                "token_hash": hash_agent_secret(token, pepper=pepper),
                "token_rotated_at": now,
                "status": "active",
                "last_seen_at": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise MonitorAgentsError(f"agent '{aid}' not found or revoked", status_code=404)
    out = _public_agent(result) or {}
    out["token"] = token
    out["rotated_at"] = now
    return out


def revoke_agent(*, tenant_id: str, agent_id: str) -> dict[str, Any]:
    """Revoke agent — blocks subsequent token auth / heartbeat."""
    tid = require_tenant_id(tenant_id)
    aid = (agent_id or "").strip()
    now = _now()
    # Rotate hash to a random value so old tokens cannot match.
    dead_hash = hash_agent_secret(f"revoked:{aid}:{secrets.token_urlsafe(16)}")
    result = _agents().find_one_and_update(
        merge_tenant_filter({"agent_id": aid}, tid),
        {
            "$set": {
                "status": "revoked",
                "revoked_at": now,
                "token_hash": dead_hash,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise MonitorAgentsError(f"agent '{aid}' not found", status_code=404)
    return _public_agent(result) or {}


def patch_agent_fields(
    *,
    tenant_id: str,
    agent_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Patch non-secret agent fields (desired-state lists, labels, etc.)."""
    tid = require_tenant_id(tenant_id)
    aid = (agent_id or "").strip()
    if not fields:
        return get_agent(tenant_id=tid, agent_id=aid)
    # Never allow token_hash / status revoke via this helper.
    blocked = {"token_hash", "code_hash", "status", "revoked_at", "tenant_id", "agent_id"}
    updates = {k: v for k, v in fields.items() if k not in blocked}
    if not updates:
        return get_agent(tenant_id=tid, agent_id=aid)
    result = _agents().find_one_and_update(
        merge_tenant_filter({"agent_id": aid}, tid),
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise MonitorAgentsError(f"agent '{aid}' not found", status_code=404)
    return _public_agent(result) or {}
