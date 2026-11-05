"""Minimal tenant + membership APIs (Master Phase 5 — isolation enforced).

Org switcher remains disabled. Current tenant comes from OIDC membership
(or migration tenant for Basic). Hard isolation is active on CMDB routes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import AuthUser, require_user
from ..config import Settings, get_settings
from ..services import memberships as memberships_service
from ..services import tenants as tenants_service
from ..services import users as users_service
from ..tenancy import (
    ISOLATION_ENFORCED,
    MIGRATION_TENANT_ID,
    ORG_SWITCHER_ENABLED,
)
from ..tenant_context import TenantContext, require_tenant

router = APIRouter(tags=["tenants"], dependencies=[Depends(require_user)])


def _resolve_local_user(user: AuthUser, settings: Settings) -> dict[str, Any] | None:
    """Best-effort local user lookup for the authenticated principal."""
    if user.auth_method == "oidc" and user.subject and settings.oidc_issuer:
        found = users_service.get_user_by_oidc(settings.oidc_issuer, user.subject)
        if found:
            return found
    if user.email:
        found = users_service.get_user_by_email(user.email)
        if found:
            return found
    return users_service.get_user_by_username(user.username)


@router.get("/api/tenants/current")
def get_current_tenant(
    tenant_ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Return the current tenant for this session (membership-resolved)."""
    tenant = tenants_service.get_tenant(tenant_ctx.tenant_id)
    if tenant is None:
        tenant = tenants_service.get_current_tenant()
    tenant["switchable"] = False
    tenant["isolation_enforced"] = ISOLATION_ENFORCED
    return {
        "tenant": tenant,
        "isolation_enforced": ISOLATION_ENFORCED,
        "org_switcher_enabled": ORG_SWITCHER_ENABLED,
        "notes": (
            "Master Phase 5: hard tenant isolation is enforced on CMDB data. "
            "Organization switching remains disabled (single-tenant UX)."
        ),
    }


@router.get("/api/tenants")
def list_tenants(
    tenant_ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """List tenants. Switcher disabled — returns current/migration tenant only."""
    tenants_service.ensure_migration_tenant()
    # Single-tenant UX: expose current tenant (not a multi-org catalog).
    current = tenants_service.get_tenant(tenant_ctx.tenant_id)
    items = [current] if current else tenants_service.list_tenants()
    for item in items:
        if item:
            item["switchable"] = False
            item["isolation_enforced"] = ISOLATION_ENFORCED
    items = [i for i in items if i]
    return {
        "items": items,
        "count": len(items),
        "default_tenant_id": MIGRATION_TENANT_ID,
        "org_switcher_enabled": ORG_SWITCHER_ENABLED,
        "isolation_enforced": ISOLATION_ENFORCED,
    }


@router.get("/api/tenants/{tenant_id}")
def get_tenant(
    tenant_id: str,
    tenant_ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    # Deny cross-tenant tenant metadata reads (404) unless it is the current tenant.
    if tenant_id != tenant_ctx.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    tenant = tenants_service.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    tenant["switchable"] = False
    tenant["isolation_enforced"] = ISOLATION_ENFORCED
    return tenant


@router.get("/api/memberships")
def list_my_memberships(
    user: AuthUser = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """List memberships for the current OIDC-linked user.

    Basic-auth migration sessions have no local identity — returns an empty list.
    """
    local = _resolve_local_user(user, settings)
    if local is None:
        return {
            "items": [],
            "count": 0,
            "user_id": None,
            "auth_method": user.auth_method,
            "org_switcher_enabled": ORG_SWITCHER_ENABLED,
            "isolation_enforced": ISOLATION_ENFORCED,
            "notes": (
                "No local user identity linked yet. OIDC login creates/links "
                "a user and a member membership on the migration tenant. "
                "HTTP Basic does not create memberships and is scoped to the "
                "migration tenant only (no tenant-auth bypass)."
            ),
        }
    items = memberships_service.list_memberships_for_user(local["user_id"])
    return {
        "items": items,
        "count": len(items),
        "user_id": local["user_id"],
        "is_platform_admin": bool(local.get("is_platform_admin")),
        "auth_method": user.auth_method,
        "org_switcher_enabled": ORG_SWITCHER_ENABLED,
        "isolation_enforced": ISOLATION_ENFORCED,
    }
