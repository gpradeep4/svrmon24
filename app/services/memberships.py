"""Tenant membership persistence (Master Phase 4).

Roles: ``member`` | ``admin`` (tenant-scoped). Platform admin is a separate
user flag set only via CLI bootstrap — never via membership create from login.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from ..db import require_database
from ..serialization import serialize_document
from ..tenancy import (
    MEMBERSHIP_ROLE_ADMIN,
    MEMBERSHIP_ROLE_MEMBER,
    MEMBERSHIP_ROLES,
    MIGRATION_TENANT_ID,
)
from . import tenants as tenants_service

COLLECTION = "memberships"


class MembershipError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _collection() -> Collection:
    coll = require_database()[COLLECTION]
    coll.create_index([("membership_id", ASCENDING)], unique=True)
    coll.create_index(
        [("tenant_id", ASCENDING), ("user_id", ASCENDING)],
        unique=True,
        name="tenant_user_unique",
    )
    coll.create_index([("user_id", ASCENDING)])
    coll.create_index([("tenant_id", ASCENDING)])
    coll.create_index([("role", ASCENDING)])
    return coll


def ensure_indexes() -> None:
    _collection()


def generate_membership_id() -> str:
    return f"mem-{uuid.uuid4().hex[:12]}"


def _normalize_role(role: str) -> str:
    value = (role or "").strip().lower()
    if value not in MEMBERSHIP_ROLES:
        raise MembershipError(
            f"Invalid membership role '{role}' (expected member|admin)",
            status_code=422,
        )
    return value


def get_membership(membership_id: str) -> dict[str, Any] | None:
    doc = _collection().find_one({"membership_id": membership_id})
    return serialize_document(doc)  # type: ignore[return-value]


def get_membership_for_user_tenant(
    user_id: str, tenant_id: str
) -> dict[str, Any] | None:
    doc = _collection().find_one({"user_id": user_id, "tenant_id": tenant_id})
    return serialize_document(doc)  # type: ignore[return-value]


def list_memberships_for_user(user_id: str) -> list[dict[str, Any]]:
    docs = list(
        _collection().find({"user_id": user_id}).sort("tenant_id", ASCENDING)
    )
    out: list[dict[str, Any]] = []
    for doc in docs:
        row = serialize_document(doc)
        assert row is not None
        tenant = tenants_service.get_tenant(row["tenant_id"])
        if tenant:
            row["tenant_display_name"] = tenant.get("display_name")
            row["tenant_switchable"] = bool(tenant.get("switchable"))
        out.append(row)
    return out


def create_membership(
    *,
    user_id: str,
    tenant_id: str,
    role: str = MEMBERSHIP_ROLE_MEMBER,
) -> dict[str, Any]:
    """Create a membership. Raises 409 if (tenant_id, user_id) already exists."""
    if not user_id:
        raise MembershipError("user_id is required", status_code=422)
    role_norm = _normalize_role(role)
    tenant = tenants_service.get_tenant(tenant_id)
    if tenant is None:
        raise MembershipError(f"Tenant '{tenant_id}' not found", status_code=404)

    coll = _collection()
    now = _now()
    doc = {
        "membership_id": generate_membership_id(),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": role_norm,
        "created_at": now,
        "updated_at": now,
    }
    try:
        coll.insert_one(doc)
    except DuplicateKeyError as exc:
        raise MembershipError(
            f"Membership already exists for user '{user_id}' in tenant '{tenant_id}'",
            status_code=409,
        ) from exc
    result = serialize_document(doc)
    assert result is not None
    result["tenant_display_name"] = tenant.get("display_name")
    return result


def ensure_membership(
    *,
    user_id: str,
    tenant_id: str = MIGRATION_TENANT_ID,
    role: str = MEMBERSHIP_ROLE_MEMBER,
    upgrade_role: bool = False,
) -> dict[str, Any]:
    """Idempotently ensure a membership exists.

    On OIDC login, call with ``role=member`` and ``upgrade_role=False`` so an
    existing admin membership is never demoted and a first login never becomes
    platform admin (platform admin is not a membership role).
    """
    role_norm = _normalize_role(role)
    tenants_service.ensure_migration_tenant()
    existing = get_membership_for_user_tenant(user_id, tenant_id)
    if existing is not None:
        if upgrade_role and role_norm == MEMBERSHIP_ROLE_ADMIN:
            if existing.get("role") != MEMBERSHIP_ROLE_ADMIN:
                _collection().update_one(
                    {"membership_id": existing["membership_id"]},
                    {"$set": {"role": MEMBERSHIP_ROLE_ADMIN, "updated_at": _now()}},
                )
                refreshed = get_membership(existing["membership_id"])
                assert refreshed is not None
                return refreshed
        return existing
    return create_membership(user_id=user_id, tenant_id=tenant_id, role=role_norm)
