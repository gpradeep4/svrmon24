"""ITSM dashboard and reports API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ...permissions import (
    PERM_ITSM_DASHBOARD_READ,
    PERM_ITSM_REPORTS_READ,
    require_permission,
)
from ...tenant_context import TenantContext
from ..services import dashboard as dashboard_service
from ..services import reports as reports_service
from ..services.reports import ReportError

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


@router.get("/export")
def dashboard_export(
    format: str = Query(default="csv", pattern="^(?i)(csv|xlsx)$"),
    window_days: int = Query(
        default=30,
        description="Export time window in days (7 or 30).",
    ),
    include_tickets: bool = Query(
        default=True,
        description="Include ticket detail rows created in the window.",
    ),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_REPORTS_READ)),
) -> Response:
    """Download summary + detail report datasets as CSV or Excel."""
    try:
        payload = reports_service.build_dashboard_export(
            tenant_id=tenant.tenant_id,
            window_days=window_days,
            include_tickets=include_tickets,
        )
        body, filename, count = reports_service.render_dashboard_export(
            payload, fmt=format.lower()
        )
    except ReportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fmt = format.lower()
    media = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if fmt == "xlsx"
        else "text/csv; charset=utf-8"
    )
    return Response(
        content=body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Count": str(count),
            "X-Export-Format": fmt,
            "Access-Control-Expose-Headers": "Content-Disposition, X-Export-Count, X-Export-Format",
        },
    )
