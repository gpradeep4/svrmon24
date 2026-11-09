"""Tenant-scoped audit event collection (Master Phase 14).

Records sensitive mutating admin / tenant / CMDB actions. Writes are
best-effort: a Mongo outage must not fail the primary request.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING

from ..db import DatabaseUnavailableError, get_database
from ..serialization import serialize_document
from ..tenancy import require_tenant_id
from ..tenant_context import TenantContext

logger = logging.getLogger(__name__)

COLLECTION = "audit_events"

# Actions we intentionally record (documentation + validation aid).
KNOWN_ACTIONS: frozenset[str] = frozenset(
    {
        "tenant.create",
        "tenant.plan_set",
        "tenant.switch",
        "membership.create",
        "component.create",
        "component.update",
        "component.delete",
        "relationship.create",
        "relationship.update",
        "relationship.delete",
        "field_definition.create",
        "field_definition.update",
        "field_definition.delete",
        "column_configuration.upsert",
        "column_configuration.reset",
        "custom_table.create",
        "custom_table.update",
        "custom_table.delete",
        "custom_table.column_add",
        "custom_table.column_update",
        "custom_table.column_delete",
        "custom_record.create",
        "custom_record.update",
        "custom_record.delete",
    }
)

_SENSITIVE_DETAIL_KEYS = frozenset(
    {
        "password",
        "client_secret",
        "secret",
        "token",
        "access_token",
        "id_token",
        "refresh_token",
        "authorization",
        "session_secret",
    }
)


class AuditError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def ensure_indexes() -> list[str]:
    """Create indexes on ``audit_events`` (idempotent)."""
    db = get_database()
    coll = db[COLLECTION]
    coll.create_index([("audit_id", ASCENDING)], unique=True, name="audit_id_unique")
    coll.create_index(
        [("tenant_id", ASCENDING), ("timestamp", DESCENDING)],
        name="tenant_timestamp_idx",
    )
    coll.create_index(
        [("tenant_id", ASCENDING), ("action", ASCENDING), ("timestamp", DESCENDING)],
        name="tenant_action_timestamp_idx",
    )
    return [
        "audit_id_unique",
        "tenant_timestamp_idx",
        "tenant_action_timestamp_idx",
    ]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_audit_id() -> str:
    return f"aud-{uuid.uuid4().hex[:16]}"


def _sanitize_details(details: dict[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}
    clean: dict[str, Any] = {}
    for key, value in details.items():
        if str(key).lower() in _SENSITIVE_DETAIL_KEYS:
            clean[str(key)] = "[redacted]"
            continue
        if isinstance(value, dict):
            clean[str(key)] = _sanitize_details(value)
        elif isinstance(value, list):
            clean[str(key)] = [
                _sanitize_details(item) if isinstance(item, dict) else item
                for item in value[:50]
            ]
        else:
            clean[str(key)] = value
    return clean


def actor_from_tenant(tenant: TenantContext) -> dict[str, Any]:
    """Build a stable actor payload from the request tenant context."""
    user = tenant.auth_user
    return {
        "username": user.username,
        "user_id": tenant.user_id,
        "auth_method": user.auth_method,
        "subject": user.subject,
        "email": user.email,
        "membership_role": tenant.membership_role,
        "is_platform_admin": tenant.is_platform_admin,
    }


def record_event(
    *,
    tenant_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    actor: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    outcome: str = "success",
    request_method: str | None = None,
    request_path: str | None = None,
) -> dict[str, Any] | None:
    """Insert one audit event. Returns the stored doc or ``None`` on failure."""
    try:
        tid = require_tenant_id(tenant_id)
    except ValueError:
        logger.warning("audit_skip invalid_tenant_id action=%s", action)
        return None

    doc: dict[str, Any] = {
        "audit_id": _new_audit_id(),
        "timestamp": _now(),
        "tenant_id": tid,
        "action": str(action),
        "resource_type": str(resource_type),
        "resource_id": resource_id,
        "actor": actor or {},
        "details": _sanitize_details(details),
        "outcome": outcome or "success",
        "request_method": request_method,
        "request_path": request_path,
    }
    try:
        db = get_database()
        db[COLLECTION].insert_one(doc)
        return serialize_document(doc)
    except DatabaseUnavailableError as exc:
        logger.warning("audit_write_skipped mongodb_unavailable detail=%s", exc)
        return None
    except Exception:  # noqa: BLE001 — never fail the primary request
        logger.exception("audit_write_failed action=%s tenant_id=%s", action, tid)
        return None


def record_from_tenant(
    tenant: TenantContext,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    outcome: str = "success",
    target_tenant_id: str | None = None,
    request_method: str | None = None,
    request_path: str | None = None,
) -> dict[str, Any] | None:
    """Convenience wrapper using the authenticated tenant context as actor."""
    return record_event(
        tenant_id=target_tenant_id or tenant.tenant_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor=actor_from_tenant(tenant),
        details=details,
        outcome=outcome,
        request_method=request_method,
        request_path=request_path,
    )


def list_events(
    *,
    tenant_id: str,
    action: str | None = None,
    resource_type: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """List audit events for one tenant (newest first)."""
    tid = require_tenant_id(tenant_id)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    query: dict[str, Any] = {"tenant_id": tid}
    if action:
        query["action"] = action.strip()
    if resource_type:
        query["resource_type"] = resource_type.strip()

    db = get_database()
    coll = db[COLLECTION]
    total = coll.count_documents(query)
    cursor = (
        coll.find(query)
        .sort([("timestamp", DESCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "tenant_id": tid,
        "collection": COLLECTION,
    }


def get_event(audit_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    """Fetch one event scoped to ``tenant_id`` (cross-tenant → None / 404)."""
    tid = require_tenant_id(tenant_id)
    db = get_database()
    doc = db[COLLECTION].find_one({"audit_id": audit_id, "tenant_id": tid})
    return serialize_document(doc)
