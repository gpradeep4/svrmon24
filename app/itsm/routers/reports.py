"""ITSM custom report definitions + export APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ...permissions import (
    PERM_ITSM_REPORTS_READ,
    PERM_ITSM_REPORTS_WRITE,
    require_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..models.reports import ReportDefinitionCreate, ReportDefinitionUpdate
from ..services import reports as reports_service
from ..services.reports import ReportError

router = APIRouter(prefix="/reports", tags=["itsm-reports"])


def _raise(exc: ReportError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


def _export_response(body: bytes, *, media: str, filename: str, count: int, fmt: str) -> Response:
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


@router.get("/definitions")
def list_report_definitions(
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_REPORTS_READ)),
) -> dict[str, Any]:
    return reports_service.list_definitions(
        tenant_id=tenant.tenant_id,
        q=q,
        page=page,
        page_size=page_size,
    )


@router.post("/definitions", status_code=201)
def create_report_definition(
    payload: ReportDefinitionCreate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_REPORTS_WRITE)),
) -> dict[str, Any]:
    try:
        doc = reports_service.create_definition(
            payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except ReportError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.report.create",
        resource_type="itsm_report_definition",
        resource_id=doc.get("report_id"),
        details={"name": doc.get("name"), "metrics": doc.get("metrics")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/definitions/{report_id}")
def get_report_definition(
    report_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_REPORTS_READ)),
) -> dict[str, Any]:
    doc = reports_service.get_definition(report_id, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Report '{report_id}' not found"
        )
    return doc


@router.patch("/definitions/{report_id}")
def update_report_definition(
    report_id: str,
    payload: ReportDefinitionUpdate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_REPORTS_WRITE)),
) -> dict[str, Any]:
    try:
        doc = reports_service.update_definition(
            report_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except ReportError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.report.update",
        resource_type="itsm_report_definition",
        resource_id=report_id,
        details=payload.model_dump(exclude_unset=True),
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.delete("/definitions/{report_id}", status_code=204)
def delete_report_definition(
    report_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_REPORTS_WRITE)),
) -> Response:
    try:
        reports_service.delete_definition(report_id, tenant_id=tenant.tenant_id)
    except ReportError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.report.delete",
        resource_type="itsm_report_definition",
        resource_id=report_id,
        details={},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return Response(status_code=204)


@router.post("/definitions/{report_id}/run")
def run_report_definition(
    report_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_REPORTS_READ)),
) -> dict[str, Any]:
    """Run a saved report with its stored filters/metrics/columns."""
    try:
        return reports_service.run_definition(
            report_id,
            tenant_id=tenant.tenant_id,
        )
    except ReportError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/definitions/{report_id}/export")
def export_report_definition(
    report_id: str,
    format: str = Query(default="csv", pattern="^(?i)(csv|xlsx)$"),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_REPORTS_READ)),
) -> Response:
    try:
        result = reports_service.run_definition(
            report_id, tenant_id=tenant.tenant_id
        )
        body, filename, count = reports_service.render_run_export(
            result, fmt=format.lower()
        )
    except ReportError as exc:
        _raise(exc)
        raise  # pragma: no cover
    fmt = format.lower()
    media = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if fmt == "xlsx"
        else "text/csv; charset=utf-8"
    )
    return _export_response(body, media=media, filename=filename, count=count, fmt=fmt)
