"""Shared tenancy constants and helpers (Master Phase 5–8 + custom entity tables).

Phase 5 makes ``tenant_id`` mandatory on CMDB collections, scopes every
read/write/aggregate, and denies cross-tenant access. ``component_id`` remains
**globally** unique. Organization switching stays disabled until multi-org UX
is explicitly enabled with isolation tests green.

Phase 6 adds typed ``cmdb_*`` collections; legacy ``components`` remains in the
tenanted set as a migration source / transitional fallback.

Phase 7 adds ``cmdb_field_definitions``; legacy ``custom_field_definitions``
remains as a migration source until cut over.

Phase 8 adds ``cmdb_column_configurations`` for tenant-scoped grid column settings.

Custom entity tables add ``cmdb_custom_table_definitions`` + ``cmdb_custom_records``.
"""

from __future__ import annotations

from typing import Any

# Locked migration tenant — stable id + display name (preferences).
MIGRATION_TENANT_ID = "tenant-svrmon24-legacy"
MIGRATION_TENANT_DISPLAY_NAME = "SVRMON24 Legacy"
MIGRATION_TENANT_SLUG = "svrmon24-legacy"

# Tenant-scoped membership roles (platform admin is a separate user flag).
MEMBERSHIP_ROLE_MEMBER = "member"
MEMBERSHIP_ROLE_ADMIN = "admin"
MEMBERSHIP_ROLES: frozenset[str] = frozenset(
    {MEMBERSHIP_ROLE_MEMBER, MEMBERSHIP_ROLE_ADMIN}
)

# Typed CMDB collections (Master Phase 6) + legacy polymorphic source.
TYPED_CMDB_COLLECTIONS: tuple[str, ...] = (
    "cmdb_servers",
    "cmdb_network",
    "cmdb_middleware",
    "cmdb_databases",
    "cmdb_applications",
)

# Collections that require tenant_id scoping.
TENANTED_COLLECTIONS: tuple[str, ...] = (
    *TYPED_CMDB_COLLECTIONS,
    "components",  # legacy polymorphic — migration source / fallback
    "cmdb_field_definitions",  # Phase 7 canonical field defs
    "custom_field_definitions",  # legacy field defs — migration source
    "cmdb_column_configurations",  # Phase 8 grid column settings
    "cmdb_custom_table_definitions",  # Custom entity table schemas
    "cmdb_custom_records",  # Custom entity rows (table_key partitioned)
    "cmdb_relationships",
    "diagnostic_history",
)

# Master Phase 5: hard isolation is on.
ISOLATION_ENFORCED = True
ORG_SWITCHER_ENABLED = False

# Match documents missing or empty tenant_id (pre-Phase-5 rows).
MISSING_TENANT_ID_FILTER: dict[str, Any] = {
    "$or": [
        {"tenant_id": {"$exists": False}},
        {"tenant_id": None},
        {"tenant_id": ""},
    ]
}


def require_tenant_id(tenant_id: str | None) -> str:
    """Return a non-empty tenant_id or raise ``ValueError``."""
    value = (tenant_id or "").strip()
    if not value:
        raise ValueError("tenant_id is required")
    return value


def tenant_filter(tenant_id: str) -> dict[str, Any]:
    """Mongo filter that scopes a query to one tenant."""
    return {"tenant_id": require_tenant_id(tenant_id)}


def merge_tenant_filter(query: dict[str, Any] | None, tenant_id: str) -> dict[str, Any]:
    """AND an existing query with mandatory ``tenant_id`` scoping."""
    scoped = tenant_filter(tenant_id)
    if not query:
        return scoped
    return {"$and": [scoped, query]}


def stamp_tenant_id(
    doc: dict[str, Any],
    *,
    tenant_id: str,
) -> dict[str, Any]:
    """Require and set ``tenant_id`` on a document being written.

    Phase 5: always stamps the caller's tenant (no optional/null dual-write).
    """
    doc["tenant_id"] = require_tenant_id(tenant_id)
    return doc
