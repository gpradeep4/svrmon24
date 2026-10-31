"""Shared tenancy constants and helpers (Master Phase 4).

Phase 4 introduces tenant / membership models and dual-writes ``tenant_id`` on
new CMDB documents. Hard cross-tenant denial is intentionally deferred to
Phase 5 — queries remain globally scoped until then.
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

# Collections that receive nullable / dual-written tenant_id in Phase 4.
TENANTED_COLLECTIONS: tuple[str, ...] = (
    "components",
    "custom_field_definitions",
    "cmdb_relationships",
    "diagnostic_history",
)


def stamp_tenant_id(
    doc: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Dual-write helper: set ``tenant_id`` when missing (does not overwrite).

    New writes stamp the migration tenant by default so Phase 5 can flip on
    mandatory scoping after a null-backfill. Existing APIs stay compatible —
    callers still look up by global ids; filters are not applied yet.
    """
    if doc.get("tenant_id") in (None, ""):
        doc["tenant_id"] = tenant_id or MIGRATION_TENANT_ID
    return doc
