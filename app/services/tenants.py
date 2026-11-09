"""Tenant persistence and migration-tenant bootstrap (Master Phase 4 / 13)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from ..db import require_database
from ..models.tenants import migration_tenant_defaults
from ..serialization import serialize_document
from ..tenancy import MIGRATION_TENANT_ID, require_tenant_id

COLLECTION = "tenants"

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class TenantError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _collection() -> Collection:
    coll = require_database()[COLLECTION]
    # Phase 5 will keep these; compound tenant-scoped uniques land later on CMDB.
    coll.create_index([("tenant_id", ASCENDING)], unique=True)
    coll.create_index([("slug", ASCENDING)], unique=True)
    return coll


def ensure_indexes() -> None:
    """Create tenant collection indexes (idempotent)."""
    _collection()


def get_tenant(tenant_id: str) -> dict[str, Any] | None:
    doc = _collection().find_one({"tenant_id": tenant_id})
    return serialize_document(doc)  # type: ignore[return-value]


def list_tenants() -> list[dict[str, Any]]:
    """List all tenants (operator / platform-admin catalog)."""
    docs = list(_collection().find().sort("display_name", ASCENDING))
    return [serialize_document(doc) for doc in docs]  # type: ignore[return-value]


def list_tenants_by_ids(tenant_ids: list[str]) -> list[dict[str, Any]]:
    """Return tenants matching the given ids (order by display_name)."""
    ids = [require_tenant_id(tid) for tid in tenant_ids if tid]
    if not ids:
        return []
    docs = list(
        _collection().find({"tenant_id": {"$in": ids}}).sort("display_name", ASCENDING)
    )
    return [serialize_document(doc) for doc in docs]  # type: ignore[return-value]


def _slugify(display_name: str, fallback: str) -> str:
    raw = (display_name or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    if not slug:
        slug = re.sub(r"[^a-z0-9]+", "-", (fallback or "").lower()).strip("-")
    if not slug:
        slug = f"org-{uuid.uuid4().hex[:8]}"
    return slug[:64]


def create_tenant(
    *,
    display_name: str,
    tenant_id: str | None = None,
    slug: str | None = None,
    plan_code: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create an organization (platform-admin / operator path).

    Does not grant memberships — callers must add members explicitly.
    """
    from . import entitlements as entitlements_service

    name = (display_name or "").strip()
    if not name:
        raise TenantError("display_name is required", status_code=422)

    tid = (tenant_id or "").strip() or f"tenant-{uuid.uuid4().hex[:12]}"
    require_tenant_id(tid)
    if tid == MIGRATION_TENANT_ID:
        raise TenantError(
            f"Cannot recreate locked migration tenant '{MIGRATION_TENANT_ID}'",
            status_code=409,
        )

    slug_value = (slug or "").strip().lower() or _slugify(name, tid)
    if not _SLUG_RE.match(slug_value):
        raise TenantError(
            "slug must be lowercase alphanumeric with optional hyphens",
            status_code=422,
        )

    plan = entitlements_service.normalize_plan_code(plan_code)
    now = _now()
    doc = {
        "tenant_id": tid,
        "display_name": name,
        "slug": slug_value,
        "status": "active",
        "is_migration_tenant": False,
        "switchable": True,
        "plan_code": plan,
        "notes": notes
        or (
            "Operator-created organization (Master Phase 13). "
            "Entitlements-only plan; no payment provider."
        ),
        "created_at": now,
        "updated_at": now,
    }
    coll = _collection()
    try:
        coll.insert_one(doc)
    except DuplicateKeyError as exc:
        raise TenantError(
            f"Tenant id or slug already exists ({tid!r} / {slug_value!r})",
            status_code=409,
        ) from exc
    return serialize_document(doc)  # type: ignore[return-value]


def set_tenant_plan(tenant_id: str, plan_code: str) -> dict[str, Any]:
    """Assign an entitlements plan_code to a tenant (no billing)."""
    from . import entitlements as entitlements_service

    tid = require_tenant_id(tenant_id)
    plan = entitlements_service.normalize_plan_code(plan_code)
    coll = _collection()
    existing = coll.find_one({"tenant_id": tid})
    if existing is None:
        raise TenantError(f"Tenant '{tid}' not found", status_code=404)
    coll.update_one(
        {"tenant_id": tid},
        {"$set": {"plan_code": plan, "updated_at": _now()}},
    )
    doc = coll.find_one({"tenant_id": tid})
    return serialize_document(doc)  # type: ignore[return-value]


def ensure_migration_tenant() -> dict[str, Any]:
    """Idempotently create the locked migration tenant ``SVRMON24 Legacy``.

    Safe to call on startup and from CLI/seed scripts. Never auto-creates
    additional organizations; additional orgs require platform-admin action.
    """
    from . import entitlements as entitlements_service

    coll = _collection()
    existing = coll.find_one({"tenant_id": MIGRATION_TENANT_ID})
    now = _now()
    defaults = migration_tenant_defaults()
    if existing is not None:
        updates = {
            "display_name": defaults["display_name"],
            "slug": defaults["slug"],
            "status": defaults["status"],
            "is_migration_tenant": True,
            # Migration org stays listed; switchability is membership-driven.
            "switchable": True,
            "notes": defaults["notes"],
            "updated_at": now,
        }
        # Preserve an explicitly assigned plan; otherwise seed default.
        if not existing.get("plan_code"):
            updates["plan_code"] = entitlements_service.DEFAULT_PLAN_CODE
        coll.update_one({"tenant_id": MIGRATION_TENANT_ID}, {"$set": updates})
        doc = coll.find_one({"tenant_id": MIGRATION_TENANT_ID})
        return serialize_document(doc)  # type: ignore[return-value]

    doc = defaults
    doc["plan_code"] = entitlements_service.DEFAULT_PLAN_CODE
    doc["created_at"] = now
    doc["updated_at"] = now
    coll.insert_one(doc)
    return serialize_document(doc)  # type: ignore[return-value]


def get_current_tenant() -> dict[str, Any]:
    """Return the migration tenant, ensuring it exists."""
    from ..tenancy import ISOLATION_ENFORCED, ORG_SWITCHER_ENABLED

    tenant = ensure_migration_tenant()
    tenant["isolation_enforced"] = ISOLATION_ENFORCED
    tenant["org_switcher_enabled"] = ORG_SWITCHER_ENABLED
    return tenant
