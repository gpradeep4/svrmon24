"""Tenant + membership APIs (Master Phase 5 isolation + Phase 13 org switcher).

Org switcher is enabled for multi-membership OIDC users. HTTP Basic remains
scoped to the migration tenant and cannot switch orgs (no tenant-auth bypass).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from ..auth import AuthUser, require_user
from ..config import Settings, get_settings
from ..services import audit as audit_service
from ..services import entitlements as entitlements_service
from ..services import memberships as memberships_service
from ..services import tenants as tenants_service
from ..services.entitlements import EntitlementError
from ..services.memberships import MembershipError
from ..services.tenants import TenantError
from ..tenancy import (
    ISOLATION_ENFORCED,
    MEMBERSHIP_ROLE_ADMIN,
    MIGRATION_TENANT_ID,
    ORG_SWITCHER_ENABLED,
    require_tenant_id,
)
from ..tenant_context import SESSION_CURRENT_TENANT, TenantContext, require_tenant

router = APIRouter(tags=["tenants"], dependencies=[Depends(require_user)])


class TenantSwitchRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1)

    @field_validator("tenant_id")
    @classmethod
    def _strip_tid(cls, value: str) -> str:
        return require_tenant_id(value)


class TenantCreateRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=120)
    tenant_id: str | None = None
    slug: str | None = None
    plan_code: str | None = None
    notes: str | None = None
    admin_user_id: str | None = Field(
        default=None,
        description="Optional local user_id to grant tenant admin membership",
    )


class TenantPlanRequest(BaseModel):
    plan_code: str = Field(..., min_length=1)


class MembershipCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: str = Field(default="member")


def _resolve_local_user(user: AuthUser, settings: Settings) -> dict[str, Any] | None:
    """Best-effort local user lookup for the authenticated principal."""
    from ..services import users as users_service

    if user.auth_method == "oidc" and user.subject and settings.oidc_issuer:
        found = users_service.get_user_by_oidc(settings.oidc_issuer, user.subject)
        if found:
            return found
    if user.email:
        found = users_service.get_user_by_email(user.email)
        if found:
            return found
    return users_service.get_user_by_username(user.username)


def _require_platform_admin(tenant_ctx: TenantContext) -> None:
    if not tenant_ctx.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin required (CLI bootstrap only)",
        )


def _require_tenant_admin(tenant_ctx: TenantContext) -> None:
    if tenant_ctx.is_platform_admin:
        return
    if tenant_ctx.membership_role == MEMBERSHIP_ROLE_ADMIN:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Tenant admin or platform admin required",
    )


def _enrich_tenant(tenant: dict[str, Any] | None) -> dict[str, Any] | None:
    if not tenant:
        return None
    tenant = dict(tenant)
    tenant["isolation_enforced"] = ISOLATION_ENFORCED
    tenant["org_switcher_enabled"] = ORG_SWITCHER_ENABLED
    # Eligible for session switch when org switcher is on.
    tenant["switchable"] = bool(ORG_SWITCHER_ENABLED and tenant.get("switchable", True))
    return tenant


@router.get("/api/tenants/current")
def get_current_tenant(
    tenant_ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Return the current tenant for this session (membership-resolved)."""
    tenant = tenants_service.get_tenant(tenant_ctx.tenant_id)
    if tenant is None:
        tenant = tenants_service.get_current_tenant()
    tenant = _enrich_tenant(tenant)
    assert tenant is not None
    return {
        "tenant": tenant,
        "isolation_enforced": ISOLATION_ENFORCED,
        "org_switcher_enabled": ORG_SWITCHER_ENABLED,
        "membership_role": tenant_ctx.membership_role,
        "is_platform_admin": tenant_ctx.is_platform_admin,
        "auth_method": tenant_ctx.auth_user.auth_method,
        "notes": (
            "Master Phase 13: hard tenant isolation remains enforced. "
            "Organization switching is available for OIDC users with multiple "
            "memberships. HTTP Basic stays on the migration tenant only."
        ),
    }


@router.get("/api/tenants")
def list_tenants(
    tenant_ctx: TenantContext = Depends(require_tenant),
    user: AuthUser = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """List organizations visible to the caller.

    - **OIDC**: tenants from local user memberships (switcher catalog).
    - **Basic**: migration tenant only (no bypass / no multi-org).
    - **Platform admin**: full catalog when listing with admin flag.
    """
    tenants_service.ensure_migration_tenant()

    if user.auth_method == "basic":
        current = tenants_service.get_tenant(MIGRATION_TENANT_ID)
        items = [_enrich_tenant(current)] if current else []
        items = [i for i in items if i]
        return {
            "items": items,
            "count": len(items),
            "default_tenant_id": MIGRATION_TENANT_ID,
            "current_tenant_id": MIGRATION_TENANT_ID,
            "org_switcher_enabled": ORG_SWITCHER_ENABLED,
            "isolation_enforced": ISOLATION_ENFORCED,
            "switchable_for_user": False,
            "notes": (
                "HTTP Basic is scoped to the migration tenant only and cannot "
                "switch organizations."
            ),
        }

    local = _resolve_local_user(user, settings)
    memberships: list[dict[str, Any]] = []
    if local and local.get("user_id"):
        memberships = memberships_service.list_memberships_for_user(
            str(local["user_id"])
        )

    role_by_tenant = {
        str(m["tenant_id"]): m.get("role")
        for m in memberships
        if m.get("tenant_id")
    }
    member_ids = list(role_by_tenant.keys())

    # Switcher catalog is always membership-scoped (switch requires membership).
    if member_ids:
        items = tenants_service.list_tenants_by_ids(member_ids)
    else:
        current = tenants_service.get_tenant(tenant_ctx.tenant_id)
        items = [current] if current else []

    enriched: list[dict[str, Any]] = []
    for item in items:
        row = _enrich_tenant(item)
        if not row:
            continue
        row["membership_role"] = role_by_tenant.get(row["tenant_id"])
        row["is_current"] = row["tenant_id"] == tenant_ctx.tenant_id
        enriched.append(row)

    catalog_items: list[dict[str, Any]] = []
    if tenant_ctx.is_platform_admin:
        # Full org catalog for admin Organizations panel (not for session switch).
        for item in tenants_service.list_tenants():
            row = _enrich_tenant(item)
            if not row:
                continue
            row["membership_role"] = role_by_tenant.get(row["tenant_id"])
            row["is_current"] = row["tenant_id"] == tenant_ctx.tenant_id
            catalog_items.append(row)

    switchable_for_user = bool(
        ORG_SWITCHER_ENABLED and len([m for m in memberships if m.get("tenant_id")]) > 1
    )
    return {
        "items": enriched,
        "count": len(enriched),
        "catalog_items": catalog_items,
        "catalog_count": len(catalog_items),
        "default_tenant_id": MIGRATION_TENANT_ID,
        "current_tenant_id": tenant_ctx.tenant_id,
        "org_switcher_enabled": ORG_SWITCHER_ENABLED,
        "isolation_enforced": ISOLATION_ENFORCED,
        "switchable_for_user": switchable_for_user,
        "membership_count": len(memberships),
        "is_platform_admin": tenant_ctx.is_platform_admin,
    }


@router.post("/api/tenants/switch")
def switch_tenant(
    body: TenantSwitchRequest,
    request: Request,
    tenant_ctx: TenantContext = Depends(require_tenant),
    user: AuthUser = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Switch the session current organization (OIDC multi-membership only)."""
    if not ORG_SWITCHER_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization switcher is disabled",
        )
    if user.auth_method == "basic":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "HTTP Basic cannot switch organizations — scoped to migration "
                "tenant only (no tenant-auth bypass)"
            ),
        )

    local = _resolve_local_user(user, settings)
    if local is None or not local.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No local user identity linked for organization switching",
        )

    target = require_tenant_id(body.tenant_id)
    membership = memberships_service.get_membership_for_user_tenant(
        str(local["user_id"]), target
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No membership for tenant '{target}'",
        )

    tenant = tenants_service.get_tenant(target)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        )

    request.session[SESSION_CURRENT_TENANT] = target
    enriched = _enrich_tenant(tenant)
    assert enriched is not None
    audit_service.record_from_tenant(
        tenant_ctx,
        action="tenant.switch",
        resource_type="tenant",
        resource_id=target,
        details={"previous_tenant_id": tenant_ctx.tenant_id},
        target_tenant_id=target,
        request_method="POST",
        request_path="/api/tenants/switch",
    )
    return {
        "ok": True,
        "tenant": enriched,
        "membership_role": membership.get("role"),
        "previous_tenant_id": tenant_ctx.tenant_id,
        "org_switcher_enabled": ORG_SWITCHER_ENABLED,
        "isolation_enforced": ISOLATION_ENFORCED,
    }


@router.post("/api/tenants", status_code=status.HTTP_201_CREATED)
def create_tenant(
    body: TenantCreateRequest,
    tenant_ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Create an organization (platform admin only)."""
    _require_platform_admin(tenant_ctx)
    try:
        tenant = tenants_service.create_tenant(
            display_name=body.display_name,
            tenant_id=body.tenant_id,
            slug=body.slug,
            plan_code=body.plan_code,
            notes=body.notes,
        )
    except TenantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except EntitlementError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    membership = None
    if body.admin_user_id:
        try:
            membership = memberships_service.ensure_membership(
                user_id=body.admin_user_id.strip(),
                tenant_id=tenant["tenant_id"],
                role=MEMBERSHIP_ROLE_ADMIN,
                upgrade_role=True,
            )
        except MembershipError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=exc.message
            ) from exc

    audit_service.record_from_tenant(
        tenant_ctx,
        action="tenant.create",
        resource_type="tenant",
        resource_id=tenant.get("tenant_id"),
        details={
            "display_name": tenant.get("display_name"),
            "plan_code": tenant.get("plan_code"),
            "admin_user_id": body.admin_user_id,
        },
        target_tenant_id=tenant.get("tenant_id"),
        request_method="POST",
        request_path="/api/tenants",
    )
    return {
        "tenant": _enrich_tenant(tenant),
        "membership": membership,
        "org_switcher_enabled": ORG_SWITCHER_ENABLED,
    }


@router.get("/api/tenants/{tenant_id}")
def get_tenant(
    tenant_id: str,
    tenant_ctx: TenantContext = Depends(require_tenant),
    user: AuthUser = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Return tenant metadata when the caller is a member (or platform admin)."""
    if tenant_ctx.is_platform_admin or tenant_id == tenant_ctx.tenant_id:
        tenant = tenants_service.get_tenant(tenant_id)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
            )
        enriched = _enrich_tenant(tenant)
        assert enriched is not None
        return enriched

    local = _resolve_local_user(user, settings)
    if local and local.get("user_id"):
        mem = memberships_service.get_membership_for_user_tenant(
            str(local["user_id"]), tenant_id
        )
        if mem is not None:
            tenant = tenants_service.get_tenant(tenant_id)
            if tenant is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
                )
            enriched = _enrich_tenant(tenant)
            assert enriched is not None
            enriched["membership_role"] = mem.get("role")
            return enriched

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")


@router.put("/api/tenants/{tenant_id}/plan")
def set_tenant_plan(
    tenant_id: str,
    body: TenantPlanRequest,
    tenant_ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Assign entitlements plan_code (platform admin only; no payment provider)."""
    _require_platform_admin(tenant_ctx)
    try:
        tenant = tenants_service.set_tenant_plan(tenant_id, body.plan_code)
    except TenantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except EntitlementError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    plan = entitlements_service.get_plan(tenant["plan_code"])
    audit_service.record_from_tenant(
        tenant_ctx,
        action="tenant.plan_set",
        resource_type="tenant",
        resource_id=tenant_id,
        details={"plan_code": tenant.get("plan_code")},
        target_tenant_id=tenant_id,
        request_method="PUT",
        request_path=f"/api/tenants/{tenant_id}/plan",
    )
    return {
        "tenant": _enrich_tenant(tenant),
        "plan": plan,
        "billing_enabled": False,
        "payment_provider": None,
    }


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
    # Basic never switches orgs (migration-tenant only; no tenant-auth bypass).
    switchable = bool(
        ORG_SWITCHER_ENABLED
        and user.auth_method != "basic"
        and len(items) > 1
    )
    return {
        "items": items,
        "count": len(items),
        "user_id": local["user_id"],
        "is_platform_admin": bool(local.get("is_platform_admin")),
        "auth_method": user.auth_method,
        "org_switcher_enabled": ORG_SWITCHER_ENABLED,
        "isolation_enforced": ISOLATION_ENFORCED,
        "switchable_for_user": switchable,
    }


@router.get("/api/tenants/{tenant_id}/members")
def list_tenant_members(
    tenant_id: str,
    tenant_ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """List members of a tenant (tenant admin of current org, or platform admin)."""
    tid = require_tenant_id(tenant_id)
    if tid != tenant_ctx.tenant_id and not tenant_ctx.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        )
    if tid == tenant_ctx.tenant_id:
        _require_tenant_admin(tenant_ctx)
    else:
        _require_platform_admin(tenant_ctx)

    items = memberships_service.list_memberships_for_tenant(tid)
    return {
        "tenant_id": tid,
        "items": items,
        "count": len(items),
        "org_switcher_enabled": ORG_SWITCHER_ENABLED,
    }


@router.post(
    "/api/tenants/{tenant_id}/members",
    status_code=status.HTTP_201_CREATED,
)
def add_tenant_member(
    tenant_id: str,
    body: MembershipCreateRequest,
    tenant_ctx: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Add a membership (tenant admin of current org, or platform admin)."""
    tid = require_tenant_id(tenant_id)
    if tid != tenant_ctx.tenant_id and not tenant_ctx.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
        )
    if tid == tenant_ctx.tenant_id:
        _require_tenant_admin(tenant_ctx)
    else:
        _require_platform_admin(tenant_ctx)

    try:
        membership = memberships_service.ensure_membership(
            user_id=body.user_id.strip(),
            tenant_id=tid,
            role=body.role,
            upgrade_role=(body.role == MEMBERSHIP_ROLE_ADMIN),
        )
    except MembershipError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    audit_service.record_from_tenant(
        tenant_ctx,
        action="membership.create",
        resource_type="membership",
        resource_id=membership.get("membership_id") if isinstance(membership, dict) else None,
        details={"user_id": body.user_id.strip(), "role": body.role, "tenant_id": tid},
        target_tenant_id=tid,
        request_method="POST",
        request_path=f"/api/tenants/{tid}/members",
    )
    return {"membership": membership, "tenant_id": tid}
