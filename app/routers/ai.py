"""Platform AI status + tenant cloud-suggestion opt-in (assist only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import require_user
from ..permissions import PERM_USERS_ADMIN, require_permission
from ..services import ai_facade as ai_facade_service
from ..services.tenants import TenantError
from ..tenant_context import TenantContext, require_tenant

router = APIRouter(
    prefix="/api/ai",
    tags=["ai"],
    dependencies=[Depends(require_user)],
)


class CloudOptInRequest(BaseModel):
    enabled: bool = Field(
        ...,
        description=(
            "Tenant opt-in for optional OpenAI-compatible cloud suggestions. "
            "Assist only — never auto-transitions or approvals. API keys stay "
            "in env/secret refs, never Mongo."
        ),
    )


@router.get("/status")
def ai_status(
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Provider enablement, entitlement, contention, and safety flags."""
    return ai_facade_service.ai_runtime_status(tenant_id=tenant.tenant_id)


@router.put("/cloud-opt-in")
def put_cloud_opt_in(
    payload: CloudOptInRequest,
    tenant: TenantContext = Depends(require_permission(PERM_USERS_ADMIN)),
) -> dict[str, Any]:
    """Toggle tenant opt-in for cloud suggestions (tenant admin)."""
    try:
        doc = ai_facade_service.set_tenant_cloud_suggestions_opt_in(
            tenant.tenant_id, payload.enabled
        )
    except TenantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    status = ai_facade_service.ai_runtime_status(tenant_id=tenant.tenant_id)
    return {
        "tenant_id": doc.get("tenant_id"),
        "ai_cloud_suggestions_opt_in": bool(doc.get("ai_cloud_suggestions_opt_in")),
        "status": status,
    }
