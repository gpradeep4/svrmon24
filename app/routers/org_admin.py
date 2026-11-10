"""Organization invites, custom roles, and invite acceptance."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import AuthUser, require_user
from ..config import Settings, get_settings
from ..permissions import PERM_USERS_ADMIN, PERM_USERS_READ, require_permission
from ..services import custom_roles as custom_roles_service
from ..services import org_invites as org_invites_service
from ..services.custom_roles import CustomRoleError
from ..services.org_invites import InviteError
from ..tenancy import require_tenant_id
from ..tenant_context import TenantContext

router = APIRouter(tags=["org-admin"], dependencies=[Depends(require_user)])


class InviteCreateRequest(BaseModel):
    invitee_email: str | None = None
    invitee_username: str | None = None
    role: str = Field(default="member")
    ttl_hours: int = Field(default=168, ge=1, le=720)


class InviteAcceptRequest(BaseModel):
    token: str = Field(..., min_length=8)


class CustomRoleCreateRequest(BaseModel):
    role_key: str = Field(..., min_length=2, max_length=32)
    display_name: str = Field(..., min_length=1, max_length=80)
    permissions: list[str] = Field(..., min_length=1)


class CustomRoleUpdateRequest(BaseModel):
    display_name: str | None = None
    permissions: list[str] | None = None


def _resolve_local_user(user: AuthUser, settings: Settings) -> dict[str, Any] | None:
    from ..services import users as users_service
    from ..services.platform_oidc import resolve_oidc_runtime

    runtime = resolve_oidc_runtime(settings)
    if user.auth_method == "oidc" and user.subject and runtime.issuer:
        found = users_service.get_user_by_oidc(runtime.issuer, user.subject)
        if found:
            return found
    if user.email:
        found = users_service.get_user_by_email(user.email)
        if found:
            return found
    return users_service.get_user_by_username(user.username)


def _tenant_scope(tenant_ctx: TenantContext, tenant_id: str) -> str:
    tid = require_tenant_id(tenant_id)
    if tid != tenant_ctx.tenant_id and not tenant_ctx.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    if tid != tenant_ctx.tenant_id:
        if not tenant_ctx.is_platform_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Platform admin required for cross-tenant org admin",
            )
    return tid


@router.get("/api/tenants/{tenant_id}/invites")
def list_tenant_invites(
    tenant_id: str,
    tenant_ctx: TenantContext = Depends(require_permission(PERM_USERS_READ)),
) -> dict[str, Any]:
    tid = _tenant_scope(tenant_ctx, tenant_id)
    items = org_invites_service.list_invites_for_tenant(tid)
    return {"tenant_id": tid, "items": items, "count": len(items)}


@router.post("/api/tenants/{tenant_id}/invites", status_code=status.HTTP_201_CREATED)
def create_tenant_invite(
    tenant_id: str,
    body: InviteCreateRequest,
    tenant_ctx: TenantContext = Depends(require_permission(PERM_USERS_ADMIN)),
) -> dict[str, Any]:
    tid = _tenant_scope(tenant_ctx, tenant_id)
    try:
        invite = org_invites_service.create_invite(
            tenant_id=tid,
            role=body.role,
            invitee_email=body.invitee_email,
            invitee_username=body.invitee_username,
            created_by_user_id=tenant_ctx.user_id,
            ttl_hours=body.ttl_hours,
        )
    except InviteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"invite": invite, "tenant_id": tid}


@router.delete("/api/tenants/{tenant_id}/invites/{invite_id}")
def revoke_tenant_invite(
    tenant_id: str,
    invite_id: str,
    tenant_ctx: TenantContext = Depends(require_permission(PERM_USERS_ADMIN)),
) -> dict[str, Any]:
    tid = _tenant_scope(tenant_ctx, tenant_id)
    try:
        invite = org_invites_service.revoke_invite(invite_id, tid)
    except InviteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"invite": invite, "tenant_id": tid}


@router.post("/api/invites/accept")
def accept_invite(
    body: InviteAcceptRequest,
    user: AuthUser = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    local = _resolve_local_user(user, settings)
    if local is None or not local.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="OIDC-linked local user required to accept invites",
        )
    try:
        result = org_invites_service.accept_invite(
            token=body.token.strip(),
            user_id=str(local["user_id"]),
            username=str(local.get("username") or user.username),
            email=local.get("email") or user.email,
        )
    except InviteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return result


@router.get("/api/tenants/{tenant_id}/custom-roles")
def list_custom_roles(
    tenant_id: str,
    tenant_ctx: TenantContext = Depends(require_permission(PERM_USERS_READ)),
) -> dict[str, Any]:
    tid = _tenant_scope(tenant_ctx, tenant_id)
    items = custom_roles_service.list_custom_roles(tid)
    return {"tenant_id": tid, "items": items, "count": len(items)}


@router.post(
    "/api/tenants/{tenant_id}/custom-roles",
    status_code=status.HTTP_201_CREATED,
)
def create_custom_role(
    tenant_id: str,
    body: CustomRoleCreateRequest,
    tenant_ctx: TenantContext = Depends(require_permission(PERM_USERS_ADMIN)),
) -> dict[str, Any]:
    tid = _tenant_scope(tenant_ctx, tenant_id)
    try:
        role = custom_roles_service.create_custom_role(
            tenant_id=tid,
            role_key=body.role_key,
            display_name=body.display_name,
            permissions=body.permissions,
        )
    except CustomRoleError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"custom_role": role, "tenant_id": tid}


@router.put("/api/tenants/{tenant_id}/custom-roles/{role_key}")
def update_custom_role(
    tenant_id: str,
    role_key: str,
    body: CustomRoleUpdateRequest,
    tenant_ctx: TenantContext = Depends(require_permission(PERM_USERS_ADMIN)),
) -> dict[str, Any]:
    tid = _tenant_scope(tenant_ctx, tenant_id)
    try:
        role = custom_roles_service.update_custom_role(
            tenant_id=tid,
            role_key=role_key,
            display_name=body.display_name,
            permissions=body.permissions,
        )
    except CustomRoleError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"custom_role": role, "tenant_id": tid}


@router.delete("/api/tenants/{tenant_id}/custom-roles/{role_key}")
def delete_custom_role(
    tenant_id: str,
    role_key: str,
    tenant_ctx: TenantContext = Depends(require_permission(PERM_USERS_ADMIN)),
) -> dict[str, Any]:
    tid = _tenant_scope(tenant_ctx, tenant_id)
    try:
        custom_roles_service.delete_custom_role(tid, role_key)
    except CustomRoleError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"ok": True, "tenant_id": tid, "role_key": role_key}
