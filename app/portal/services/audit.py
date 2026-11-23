"""Service Portal audit — ``sp_audit_events`` + platform ``audit_events`` (SP7)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...services import audit as platform_audit
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from .indexes import AUDIT_EVENTS, ensure_portal_indexes

logger = logging.getLogger(__name__)

_SENSITIVE = frozenset(
    {
        "password",
        "secret",
        "token",
        "client_secret",
        "access_token",
        "authorization",
        "secret_ref",
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_portal_indexes()
    return require_itsm_database()[AUDIT_EVENTS]


def _new_id() -> str:
    return f"SPA-{uuid.uuid4().hex[:12].upper()}"


def _sanitize(details: dict[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}
    out: dict[str, Any] = {}
    for key, value in details.items():
        lk = str(key).lower()
        if lk in _SENSITIVE or lk.endswith("_secret") or "password" in lk:
            out[str(key)] = "[redacted]"
        elif isinstance(value, dict):
            out[str(key)] = _sanitize(value)
        else:
            out[str(key)] = value
    return out


def record_portal_event(
    *,
    tenant_id: str,
    action: str,
    actor: dict[str, Any] | None = None,
    request_id: str | None = None,
    change_id: str | None = None,
    resource_type: str = "sp_request",
    resource_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Best-effort dual write: portal collection + platform audit."""
    try:
        tid = require_tenant_id(tenant_id)
    except ValueError:
        return None

    actor = actor or {}
    doc: dict[str, Any] = {
        "event_id": _new_id(),
        "action": str(action),
        "request_id": request_id,
        "change_id": change_id,
        "resource_type": resource_type,
        "resource_id": resource_id or request_id or change_id,
        "actor": {
            "user_id": actor.get("user_id"),
            "username": actor.get("username"),
        },
        "before": _sanitize(before),
        "after": _sanitize(after),
        "details": _sanitize(details),
        "created_at": _now(),
    }
    stamp_tenant_id(doc, tenant_id=tid)
    try:
        _coll().insert_one(doc)
    except Exception:  # noqa: BLE001
        logger.exception("portal_audit_write_failed action=%s", action)

    platform_audit.record_event(
        tenant_id=tid,
        action=action,
        resource_type=resource_type,
        resource_id=doc.get("resource_id"),
        actor=actor,
        details={
            **_sanitize(details),
            "request_id": request_id,
            "change_id": change_id,
        },
    )
    return serialize_document(doc)


def list_portal_events(
    *,
    tenant_id: str,
    action: str | None = None,
    request_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    clauses: list[dict[str, Any]] = []
    if action:
        clauses.append({"action": action})
    if request_id:
        clauses.append({"request_id": request_id})
    base = {"$and": clauses} if clauses else None
    query = merge_tenant_filter(base, tid)
    coll = _coll()
    total = coll.count_documents(query)
    skip = max(0, (page - 1) * page_size)
    cursor = (
        coll.find(query)
        .sort([("created_at", -1)])
        .skip(skip)
        .limit(page_size)
    )
    return {
        "items": [serialize_document(d) for d in cursor],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
