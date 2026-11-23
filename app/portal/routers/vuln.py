"""Vulnerability report APIs (SP11)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...permissions import PERM_SP_EXECUTION_READ, PERM_SP_REQUEST_READ, require_permission
from ...tenant_context import TenantContext
from ..services import vuln as vuln_service
from ..services.vuln import VulnError

router = APIRouter(prefix="/vuln", tags=["portal-vuln"])


def _raise(exc: VulnError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/reports")
def list_vuln_reports(
    request_id: str | None = Query(default=None),
    component_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_SP_EXECUTION_READ)),
) -> dict[str, Any]:
    try:
        return vuln_service.list_reports(
            tenant_id=tenant.tenant_id,
            request_id=request_id,
            component_id=component_id,
            page=page,
            page_size=page_size,
        )
    except VulnError as exc:
        _raise(exc)
    return {}


@router.get("/reports/{report_id}")
def get_vuln_report(
    report_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_SP_REQUEST_READ)),
) -> dict[str, Any]:
    try:
        return vuln_service.get_report(
            tenant_id=tenant.tenant_id, report_id=report_id
        )
    except VulnError as exc:
        _raise(exc)
    return {}
