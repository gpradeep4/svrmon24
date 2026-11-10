"""Tenant membership persistence (Master Phase 4 + RBAC).

Roles: ``viewer`` | ``member`` | ``admin`` | ``owner`` (tenant-scoped).
Platform admin is a separate user flag set only via CLI bootstrap — never via
membership create from login.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from ..db import require_database
from ..permissions import ROLE_RANK, normalize_membership_role
from ..serialization import serialize_document
from ..tenancy import (
    MEMBERSHIP_ROLE_MEMBER,
    MEMBERSHIP_ROLE_OWNER,
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


def _normalize_role(role: str, *, tenant_id: str | None = None) -> str:
    try:
        return normalize_membership_role(role, tenant_id=tenant_id)
    except ValueError as exc:
        raise MembershipError(str(exc), status_code=422) from exc


def _role_rank(role: str, *, tenant_id: str | None = None) -> int:
    from ..permissions import _role_rank as perm_rank

    try:
        norm = normalize_membership_role(role, tenant_id=tenant_id)
    except ValueError:
        return 0
    return perm_rank(norm, tenant_id=tenant_id)


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
            row["tenant_switchable"] = bool(tenant.get("switchable", True))
            row["plan_code"] = tenant.get("plan_code")
        out.append(row)
    return out


def list_memberships_for_tenant(tenant_id: str) -> list[dict[str, Any]]:
    """List memberships for one tenant (Users panel / tenant admin)."""
    from . import users as users_service

    tid = (tenant_id or "").strip()
    if not tid:
        raise MembershipError("tenant_id is required", status_code=422)
    docs = list(
        _collection().find({"tenant_id": tid}).sort("created_at", ASCENDING)
    )
    out: list[dict[str, Any]] = []
    for doc in docs:
        row = serialize_document(doc)
        assert row is not None
        user = users_service.get_user(row["user_id"])
        if user:
            row["username"] = user.get("username")
            row["email"] = user.get("email")
            row["display_name"] = user.get("display_name")
            row["is_platform_admin"] = bool(user.get("is_platform_admin"))
        else:
            row["username"] = None
            row["email"] = None
            row["display_name"] = None
            row["is_platform_admin"] = False
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
    role_norm = _normalize_role(role, tenant_id=tenant_id)
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
    existing admin/owner membership is never demoted and a first login never
    becomes platform admin (platform admin is not a membership role).
    """
    role_norm = _normalize_role(role, tenant_id=tenant_id)
    tenants_service.ensure_migration_tenant()
    existing = get_membership_for_user_tenant(user_id, tenant_id)
    if existing is not None:
        if upgrade_role and _role_rank(role_norm, tenant_id=tenant_id) > _role_rank(
            str(existing.get("role") or MEMBERSHIP_ROLE_MEMBER),
            tenant_id=tenant_id,
        ):
            return update_membership_role(
                membership_id=str(existing["membership_id"]),
                role=role_norm,
            )
        return existing
    return create_membership(user_id=user_id, tenant_id=tenant_id, role=role_norm)


def update_membership_role(
    *,
    membership_id: str,
    role: str,
) -> dict[str, Any]:
    """Update the role on an existing membership."""
    mid = (membership_id or "").strip()
    if not mid:
        raise MembershipError("membership_id is required", status_code=422)
    existing = get_membership(mid)
    if existing is None:
        raise MembershipError(f"Membership '{mid}' not found", status_code=404)
    role_norm = _normalize_role(role, tenant_id=str(existing.get("tenant_id") or ""))
    _collection().update_one(
        {"membership_id": mid},
        {"$set": {"role": role_norm, "updated_at": _now()}},
    )
    refreshed = get_membership(mid)
    assert refreshed is not None
    return refreshed


def count_owners(tenant_id: str) -> int:
    tid = (tenant_id or "").strip()
    if not tid:
        return 0
    return int(
        _collection().count_documents(
            {"tenant_id": tid, "role": MEMBERSHIP_ROLE_OWNER}
        )
    )
