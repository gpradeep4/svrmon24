"""Monitoring targets API — sync from CMDB + domain health listing (SIMULATED)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...permissions import (
    PERM_MONITOR_TARGETS_READ,
    PERM_MONITOR_TARGETS_WRITE,
    require_permission,
)
from ...services import audit as audit_service
from ...services.entitlements import EntitlementError
from ...tenant_context import TenantContext
from ..services import targets as targets_service
from ..services.targets import MonitorTargetsError

router = APIRouter(tags=["monitor-targets"])


def _raise(exc: MonitorTargetsError | EntitlementError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/targets")
def list_targets(
    q: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    target_kind: str | None = Query(default=None),
    os_family: str | None = Query(default=None),
    collect_mode: str | None = Query(default=None),
    status: str | None = Query(default=None),
    component_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_READ)),
) -> dict[str, Any]:
    try:
        return targets_service.list_targets(
            tenant_id=tenant.tenant_id,
            q=q,
            domain=domain,
            target_kind=target_kind,
            os_family=os_family,
            collect_mode=collect_mode,
            status=status,
            component_id=component_id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except MonitorTargetsError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/targets/sync-from-cmdb")
def sync_from_cmdb(
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_WRITE)),
) -> dict[str, Any]:
    """Upsert monitor targets from same-tenant CMDB CIs (service client only)."""
    try:
        result = targets_service.sync_from_cmdb(tenant_id=tenant.tenant_id)
    except EntitlementError as exc:
        _raise(exc)
        raise  # pragma: no cover
    except MonitorTargetsError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.targets.sync_from_cmdb",
        resource_type="monitor_targets",
        resource_id=tenant.tenant_id,
        details={
            "created": result.get("created"),
            "updated": result.get("updated"),
            "skipped": result.get("skipped"),
            "entitlement_truncated": result.get("entitlement_truncated"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return result


@router.get("/targets/{target_id}")
def get_target(
    target_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_READ)),
) -> dict[str, Any]:
    doc = targets_service.get_target(
        tenant_id=tenant.tenant_id, target_id=target_id
    )
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Target '{target_id}' not found"
        )
    metrics = targets_service.list_metrics(
        tenant_id=tenant.tenant_id,
        target_id=target_id,
        page=1,
        page_size=12,
        latest_only=True,
    )
    doc["latest_metrics"] = metrics.get("items") or []
    return doc


@router.get("/targets/{target_id}/suggest-check")
def suggest_check(
    target_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_READ)),
) -> dict[str, Any]:
    """Return an HTTP/TCP check draft from CMDB Middleware listen fields.

    Does not create a check — human saves via ``POST /api/monitor/checks``.
    """
    try:
        return targets_service.suggest_check_from_cmdb(
            tenant_id=tenant.tenant_id, target_id=target_id
        )
    except MonitorTargetsError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/targets/{target_id}/metrics")
def list_target_metrics(
    target_id: str,
    metric_name: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    latest_only: bool = Query(default=False),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_READ)),
) -> dict[str, Any]:
    try:
        return targets_service.list_metrics(
            tenant_id=tenant.tenant_id,
            target_id=target_id,
            metric_name=metric_name,
            page=page,
            page_size=page_size,
            latest_only=latest_only,
        )
    except MonitorTargetsError as exc:
        _raise(exc)
        raise  # pragma: no cover
