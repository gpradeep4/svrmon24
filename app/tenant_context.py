"""Resolve the current tenant for an authenticated request (Master Phase 5).

OIDC sessions pick a tenant from membership (session override when valid).
HTTP Basic is scoped to the migration tenant only — it must never bypass
tenant authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from .auth import AuthUser, require_user
from .config import Settings, get_settings
from .db import DatabaseUnavailableError, ping_database
from .tenancy import (
    ISOLATION_ENFORCED,
    MIGRATION_TENANT_DISPLAY_NAME,
    MIGRATION_TENANT_ID,
    ORG_SWITCHER_ENABLED,
    require_tenant_id,
)

SESSION_CURRENT_TENANT = "current_tenant_id"


@dataclass(frozen=True)
class TenantContext:
    """Authenticated request scoped to a single tenant."""

    tenant_id: str
    auth_user: AuthUser
    user_id: str | None = None
    membership_role: str | None = None
    is_platform_admin: bool = False
    tenant_display_name: str = MIGRATION_TENANT_DISPLAY_NAME

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "tenant_display_name": self.tenant_display_name,
            "user_id": self.user_id,
            "membership_role": self.membership_role,
            "is_platform_admin": self.is_platform_admin,
            "auth_method": self.auth_user.auth_method,
            "isolation_enforced": ISOLATION_ENFORCED,
            "org_switcher_enabled": ORG_SWITCHER_ENABLED,
        }


def _resolve_local_user(user: AuthUser, settings: Settings) -> dict[str, Any] | None:
    from .services import users as users_service

    if user.auth_method == "oidc" and user.subject and settings.oidc_issuer:
        found = users_service.get_user_by_oidc(settings.oidc_issuer, user.subject)
        if found:
            return found
    if user.email:
        found = users_service.get_user_by_email(user.email)
        if found:
            return found
    return users_service.get_user_by_username(user.username)


def _tenant_display(tenant_id: str) -> str:
    from .services import tenants as tenants_service

    tenant = tenants_service.get_tenant(tenant_id)
    if tenant and tenant.get("display_name"):
        return str(tenant["display_name"])
    if tenant_id == MIGRATION_TENANT_ID:
        return MIGRATION_TENANT_DISPLAY_NAME
    return tenant_id


def _pick_tenant_id(
    *,
    request: Request,
    memberships: list[dict[str, Any]],
) -> tuple[str, str | None]:
    """Choose current tenant from session (if membership allows) or defaults."""
    member_ids = {
        str(m.get("tenant_id"))
        for m in memberships
        if m.get("tenant_id")
    }
    role_by_tenant = {
        str(m.get("tenant_id")): str(m.get("role") or "")
        for m in memberships
        if m.get("tenant_id")
    }

    session_tid = request.session.get(SESSION_CURRENT_TENANT)
    if isinstance(session_tid, str) and session_tid in member_ids:
        return session_tid, role_by_tenant.get(session_tid)

    if MIGRATION_TENANT_ID in member_ids:
        return MIGRATION_TENANT_ID, role_by_tenant.get(MIGRATION_TENANT_ID)

    if memberships:
        tid = str(memberships[0]["tenant_id"])
        return tid, role_by_tenant.get(tid)

    # OIDC without membership yet — fall back to migration tenant (login links it).
    return MIGRATION_TENANT_ID, None


def require_tenant(
    request: Request,
    user: Annotated[AuthUser, Depends(require_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TenantContext:
    """Resolve tenant scope for CMDB / dashboard / diagnostic routes.

    - **OIDC**: current tenant from membership (+ optional session selection).
    - **Basic**: always the migration tenant (shared credential; still scoped —
      never a cross-tenant bypass).
    """
    # Basic auth coexistence: scoped to migration tenant only.
    if user.auth_method == "basic":
        request.session[SESSION_CURRENT_TENANT] = MIGRATION_TENANT_ID
        return TenantContext(
            tenant_id=MIGRATION_TENANT_ID,
            auth_user=user,
            user_id=None,
            membership_role=None,
            is_platform_admin=False,
            tenant_display_name=MIGRATION_TENANT_DISPLAY_NAME,
        )

    db_status = ping_database(settings)
    if not db_status.get("ok"):
        # Fail closed for data routes when Mongo is down after auth — callers
        # that need DB will raise DatabaseUnavailableError from services.
        request.session[SESSION_CURRENT_TENANT] = MIGRATION_TENANT_ID
        return TenantContext(
            tenant_id=MIGRATION_TENANT_ID,
            auth_user=user,
            tenant_display_name=MIGRATION_TENANT_DISPLAY_NAME,
        )

    try:
        from .services import memberships as memberships_service
        from .services import tenants as tenants_service

        tenants_service.ensure_migration_tenant()
        local = _resolve_local_user(user, settings)
        memberships: list[dict[str, Any]] = []
        user_id = None
        is_platform_admin = False
        if local is not None:
            user_id = local.get("user_id")
            is_platform_admin = bool(local.get("is_platform_admin"))
            if user_id:
                memberships = memberships_service.list_memberships_for_user(
                    str(user_id)
                )

        tenant_id, role = _pick_tenant_id(request=request, memberships=memberships)
        tenant_id = require_tenant_id(tenant_id)
        request.session[SESSION_CURRENT_TENANT] = tenant_id
        return TenantContext(
            tenant_id=tenant_id,
            auth_user=user,
            user_id=str(user_id) if user_id else None,
            membership_role=role,
            is_platform_admin=is_platform_admin,
            tenant_display_name=_tenant_display(tenant_id),
        )
    except DatabaseUnavailableError:
        return TenantContext(
            tenant_id=MIGRATION_TENANT_ID,
            auth_user=user,
            tenant_display_name=MIGRATION_TENANT_DISPLAY_NAME,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc) or "No tenant membership for this principal",
        ) from exc


def assert_same_tenant(doc: dict[str, Any] | None, tenant_id: str) -> dict[str, Any] | None:
    """Return ``doc`` only when it belongs to ``tenant_id``; else ``None`` (404 path)."""
    if doc is None:
        return None
    if str(doc.get("tenant_id") or "") != require_tenant_id(tenant_id):
        return None
    return doc
