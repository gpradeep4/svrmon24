"""ITSM dashboard stub API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...permissions import PERM_ITSM_DASHBOARD_READ, require_permission
from ...tenant_context import TenantContext
from ..services import dashboard as dashboard_service

router = APIRouter(prefix="/dashboard", tags=["itsm-dashboard"])


@router.get("/summary")
def dashboard_summary(
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_DASHBOARD_READ)),
) -> dict[str, Any]:
    return dashboard_service.summary(tenant_id=tenant.tenant_id)
