"""Tenant persistence and migration-tenant bootstrap (Master Phase 4)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection

from ..db import require_database
from ..models.tenants import migration_tenant_defaults
from ..serialization import serialize_document
from ..tenancy import MIGRATION_TENANT_ID

COLLECTION = "tenants"


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
    """List tenants. Phase 4 stays single-logical-org (migration tenant only)."""
    docs = list(_collection().find().sort("display_name", ASCENDING))
    return [serialize_document(doc) for doc in docs]  # type: ignore[return-value]


def ensure_migration_tenant() -> dict[str, Any]:
    """Idempotently create the locked migration tenant ``SVRMON24 Legacy``.

    Safe to call on startup and from CLI/seed scripts. Never creates additional
    organizations or enables org switching.
    """
    coll = _collection()
    existing = coll.find_one({"tenant_id": MIGRATION_TENANT_ID})
    now = _now()
    if existing is not None:
        # Keep display name / flags consistent with locked decisions.
        defaults = migration_tenant_defaults()
        updates = {
            "display_name": defaults["display_name"],
            "slug": defaults["slug"],
            "status": defaults["status"],
            "is_migration_tenant": True,
            "switchable": False,
            "notes": defaults["notes"],
            "updated_at": now,
        }
        coll.update_one({"tenant_id": MIGRATION_TENANT_ID}, {"$set": updates})
        doc = coll.find_one({"tenant_id": MIGRATION_TENANT_ID})
        return serialize_document(doc)  # type: ignore[return-value]

    doc = migration_tenant_defaults()
    doc["created_at"] = now
    doc["updated_at"] = now
    coll.insert_one(doc)
    return serialize_document(doc)  # type: ignore[return-value]


def get_current_tenant() -> dict[str, Any]:
    """Return the migration tenant, ensuring it exists."""
    tenant = ensure_migration_tenant()
    # Explicit UX signal: not switchable in Phase 4.
    tenant["switchable"] = False
    tenant["isolation_enforced"] = False
    return tenant
