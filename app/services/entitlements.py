"""Tenant entitlements (plan limits only — Master Phase 9).

v1 is entitlements-only: no payment provider, no billing webhooks, no Stripe.
Plans describe soft/hard resource ceilings that services may enforce. The
migration / default plan is unlimited so existing tenants keep working until
operators assign a limited plan later.
"""

from __future__ import annotations

from typing import Any

from ..tenancy import require_tenant_id

# Resource keys services may check. None in limits → unlimited.
RESOURCE_RELATIONSHIPS = "relationships"
RESOURCE_COMPONENTS = "components"
RESOURCE_CUSTOM_TABLES = "custom_tables"
RESOURCE_CUSTOM_RECORDS = "custom_records"

PLAN_LEGACY_UNLIMITED = "legacy_unlimited"

# In-memory plan catalog (no payment system). Operators can later replace this
# with tenant document fields without inventing checkout/billing.
_PLAN_CATALOG: dict[str, dict[str, Any]] = {
    PLAN_LEGACY_UNLIMITED: {
        "plan_code": PLAN_LEGACY_UNLIMITED,
        "plan_label": "Legacy (unlimited)",
        "limits": {
            RESOURCE_RELATIONSHIPS: None,
            RESOURCE_COMPONENTS: None,
            RESOURCE_CUSTOM_TABLES: None,
            RESOURCE_CUSTOM_RECORDS: None,
        },
        "notes": (
            "Default entitlements for all tenants in v1. "
            "No payment provider is wired; limits are advisory until assigned."
        ),
    },
}


class EntitlementError(Exception):
    def __init__(self, message: str, *, status_code: int = 403) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _plan_for_tenant(_tenant_id: str) -> dict[str, Any]:
    """Resolve plan for a tenant. v1: always legacy unlimited."""
    return dict(_PLAN_CATALOG[PLAN_LEGACY_UNLIMITED])


def get_tenant_entitlements(tenant_id: str) -> dict[str, Any]:
    """Return entitlements snapshot for the current tenant (no billing fields)."""
    tid = require_tenant_id(tenant_id)
    plan = _plan_for_tenant(tid)
    return {
        "tenant_id": tid,
        "plan_code": plan["plan_code"],
        "plan_label": plan["plan_label"],
        "payment_provider": None,
        "billing_enabled": False,
        "limits": dict(plan["limits"]),
        "notes": plan["notes"],
    }


def relationship_limit(tenant_id: str) -> int | None:
    """Max relationships allowed for tenant, or None when unlimited."""
    entitlements = get_tenant_entitlements(tenant_id)
    limit = entitlements["limits"].get(RESOURCE_RELATIONSHIPS)
    if limit is None:
        return None
    return int(limit)


def assert_can_create_relationship(tenant_id: str) -> None:
    """Enforce relationship create against tenant entitlements.

    Unlimited (None) always passes. When a numeric limit is set, count current
    tenant relationships and raise EntitlementError (403) at/over the ceiling.
    """
    tid = require_tenant_id(tenant_id)
    limit = relationship_limit(tid)
    if limit is None:
        return

    from . import relationships as relationships_service

    listed = relationships_service.list_relationships(
        tenant_id=tid, page=1, page_size=1
    )
    total = int(listed.get("total") or 0)
    if total >= limit:
        raise EntitlementError(
            f"Relationship limit reached for this tenant "
            f"({total}/{limit}). Upgrade entitlements to create more.",
            status_code=403,
        )
