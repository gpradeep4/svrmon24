"""Tenant-defined custom roles (permission subsets)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from ..db import require_database
from ..permissions import ALL_PERMISSIONS
from ..serialization import serialize_document

COLLECTION = "custom_roles"
ROLE_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")
CUSTOM_ROLE_PREFIX = "custom:"


class CustomRoleError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _collection():
    coll = require_database()[COLLECTION]
    coll.create_index([("custom_role_id", ASCENDING)], unique=True)
    coll.create_index(
        [("tenant_id", ASCENDING), ("role_key", ASCENDING)],
        unique=True,
        name="tenant_role_key_unique",
    )
    return coll


def ensure_indexes() -> None:
    _collection()


def is_custom_role(role: str | None) -> bool:
    return bool(role and str(role).startswith(CUSTOM_ROLE_PREFIX))


def custom_role_key(role: str) -> str:
    return str(role)[len(CUSTOM_ROLE_PREFIX) :]


def membership_role_for_custom(role_key: str) -> str:
    return f"{CUSTOM_ROLE_PREFIX}{role_key}"


def validate_role_key(role_key: str) -> str:
    value = (role_key or "").strip().lower()
    if not ROLE_KEY_RE.match(value):
        raise CustomRoleError(
            "role_key must match ^[a-z][a-z0-9_-]{1,30}$",
            status_code=422,
        )
    return value


def validate_permissions(permissions: list[str]) -> list[str]:
    if not permissions:
        raise CustomRoleError("permissions must be non-empty", status_code=422)
    unknown = sorted(set(permissions) - set(ALL_PERMISSIONS))
    if unknown:
        raise CustomRoleError(
            f"Unknown permissions: {', '.join(unknown)}",
            status_code=422,
        )
    return sorted(set(permissions))


def generate_custom_role_id() -> str:
    return f"crole-{uuid.uuid4().hex[:12]}"


def list_custom_roles(tenant_id: str) -> list[dict[str, Any]]:
    docs = list(
        _collection().find({"tenant_id": tenant_id}).sort("role_key", ASCENDING)
    )
    return [serialize_document(d) for d in docs if serialize_document(d)]


def get_custom_role(tenant_id: str, role_key: str) -> dict[str, Any] | None:
    key = validate_role_key(role_key)
    doc = _collection().find_one({"tenant_id": tenant_id, "role_key": key})
    return serialize_document(doc)  # type: ignore[return-value]


def get_custom_role_by_membership_role(tenant_id: str, membership_role: str) -> dict[str, Any] | None:
    if not is_custom_role(membership_role):
        return None
    return get_custom_role(tenant_id, custom_role_key(membership_role))


def create_custom_role(
    *,
    tenant_id: str,
    role_key: str,
    display_name: str,
    permissions: list[str],
) -> dict[str, Any]:
    key = validate_role_key(role_key)
    perms = validate_permissions(permissions)
    name = (display_name or "").strip()
    if not name:
        raise CustomRoleError("display_name is required", status_code=422)
    now = _now()
    doc = {
        "custom_role_id": generate_custom_role_id(),
        "tenant_id": tenant_id,
        "role_key": key,
        "display_name": name,
        "permissions": perms,
        "membership_role": membership_role_for_custom(key),
        "created_at": now,
        "updated_at": now,
    }
    try:
        _collection().insert_one(doc)
    except DuplicateKeyError as exc:
        raise CustomRoleError(
            f"Custom role '{key}' already exists in this tenant",
            status_code=409,
        ) from exc
    return serialize_document(doc)  # type: ignore[return-value]


def update_custom_role(
    *,
    tenant_id: str,
    role_key: str,
    display_name: str | None = None,
    permissions: list[str] | None = None,
) -> dict[str, Any]:
    existing = get_custom_role(tenant_id, role_key)
    if existing is None:
        raise CustomRoleError("Custom role not found", status_code=404)
    updates: dict[str, Any] = {"updated_at": _now()}
    if display_name is not None:
        name = display_name.strip()
        if not name:
            raise CustomRoleError("display_name cannot be empty", status_code=422)
        updates["display_name"] = name
    if permissions is not None:
        updates["permissions"] = validate_permissions(permissions)
    _collection().update_one(
        {"tenant_id": tenant_id, "role_key": validate_role_key(role_key)},
        {"$set": updates},
    )
    refreshed = get_custom_role(tenant_id, role_key)
    assert refreshed is not None
    return refreshed


def delete_custom_role(tenant_id: str, role_key: str) -> None:
    key = validate_role_key(role_key)
    result = _collection().delete_one({"tenant_id": tenant_id, "role_key": key})
    if result.deleted_count != 1:
        raise CustomRoleError("Custom role not found", status_code=404)
