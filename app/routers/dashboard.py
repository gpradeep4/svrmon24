"""Dashboard summary API — live aggregates for the UI (tenant-scoped)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..auth import require_user
from ..services import dashboard as dashboard_service
from ..tenant_context import TenantContext, require_tenant

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_user)],
)


@router.get("/summary")
def dashboard_summary(
    recent_limit: int = Query(default=8, ge=1, le=50),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Return live dashboard widget data (no hardcoded counts)."""
    return dashboard_service.get_dashboard_summary(
        tenant_id=tenant.tenant_id, recent_limit=recent_limit
    )
