"""Minimal tenant + membership APIs (Master Phase 4).

Single logical org: the migration tenant is listed/returned as non-switchable.
Hard isolation is Phase 5 — these endpoints do not claim cross-tenant denial.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth import AuthUser, require_user
from ..config import Settings, get_settings
from ..services import memberships as memberships_service
from ..services import tenants as tenants_service
from ..services import users as users_service
from ..tenancy import MIGRATION_TENANT_ID

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
def get_current_tenant(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    """Return the current (migration) tenant — single logical org, not switchable."""
    tenant = tenants_service.get_current_tenant()
    return {
        "tenant": tenant,
        "isolation_enforced": False,
        "notes": (
            "Master Phase 4: tenant models only. Organization switching and "
            "hard cross-tenant denial are not active."
        ),
    }


@router.get("/api/tenants")
def list_tenants(_user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    """List tenants visible in this phase (migration tenant only)."""
    tenants_service.ensure_migration_tenant()
    items = tenants_service.list_tenants()
    for item in items:
        item["switchable"] = False
    return {
        "items": items,
        "count": len(items),
        "default_tenant_id": MIGRATION_TENANT_ID,
        "org_switcher_enabled": False,
        "isolation_enforced": False,
    }


@router.get("/api/tenants/{tenant_id}")
def get_tenant(tenant_id: str, _user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    tenant = tenants_service.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    tenant["switchable"] = False
    tenant["isolation_enforced"] = False
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
            "notes": (
                "No local user identity linked yet. OIDC login creates/links "
                "a user and a member membership on the migration tenant. "
                "HTTP Basic does not create memberships."
            ),
        }
    items = memberships_service.list_memberships_for_user(local["user_id"])
    return {
        "items": items,
        "count": len(items),
        "user_id": local["user_id"],
        "is_platform_admin": bool(local.get("is_platform_admin")),
        "auth_method": user.auth_method,
        "org_switcher_enabled": False,
        "isolation_enforced": False,
    }
