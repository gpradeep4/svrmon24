"""Platform operator APIs (platform admin only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..permissions import require_permission, PERM_PLANS_ADMIN
from ..services.platform_oidc import PlatformOidcError, public_oidc_settings, upsert_oidc_settings
from ..tenant_context import TenantContext

router = APIRouter(tags=["platform"], dependencies=[Depends(require_permission(PERM_PLANS_ADMIN))])


def _require_platform_admin(tenant_ctx: TenantContext) -> None:
    if not tenant_ctx.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin required",
        )


class PlatformOidcUpdate(BaseModel):
    oidc_enabled: bool | None = None
    issuer: str | None = None
    client_id: str | None = None
    redirect_uri: str | None = None
    scopes: str | None = None
    client_secret_env_ref: str | None = Field(
        default=None,
        description="Environment variable name that holds the client secret (never the secret itself)",
    )
    active: bool = True


@router.get("/api/platform/oidc-settings")
def get_platform_oidc_settings(
    tenant_ctx: TenantContext = Depends(require_permission(PERM_PLANS_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _require_platform_admin(tenant_ctx)
    return public_oidc_settings(settings)


@router.put("/api/platform/oidc-settings")
def put_platform_oidc_settings(
    body: PlatformOidcUpdate,
    tenant_ctx: TenantContext = Depends(require_permission(PERM_PLANS_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _require_platform_admin(tenant_ctx)
    try:
        upsert_oidc_settings(
            oidc_enabled=body.oidc_enabled,
            issuer=body.issuer,
            client_id=body.client_id,
            redirect_uri=body.redirect_uri,
            scopes=body.scopes,
            client_secret_env_ref=body.client_secret_env_ref,
            active=body.active,
        )
    except PlatformOidcError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return public_oidc_settings(settings)
