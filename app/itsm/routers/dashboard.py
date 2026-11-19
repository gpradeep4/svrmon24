"""ITSM dashboard and reports API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...permissions import PERM_ITSM_DASHBOARD_READ, require_permission
from ...tenant_context import TenantContext
from ..services import dashboard as dashboard_service

router = APIRouter(prefix="/dashboard", tags=["itsm-dashboard"])


@router.get("/summary")
def dashboard_summary(
    window_days: int | None = Query(
        default=None,
        description="Optional created/resolved window: 7 or 30 days. Omit for all-time snapshot KPIs only.",
    ),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_DASHBOARD_READ)),
) -> dict[str, Any]:
    try:
        return dashboard_service.summary(
            tenant_id=tenant.tenant_id,
            window_days=window_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/reports")
def dashboard_reports(
    window_days: int = Query(
        default=30,
        description="Reports time window in days (7 or 30).",
    ),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_DASHBOARD_READ)),
) -> dict[str, Any]:
    try:
        return dashboard_service.reports(
            tenant_id=tenant.tenant_id,
            window_days=window_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
