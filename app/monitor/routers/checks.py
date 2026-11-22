"""Agentless monitor checks CRUD + run-once + results (L1)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...config import Settings, get_settings
from ...permissions import (
    PERM_MONITOR_TARGETS_READ,
    PERM_MONITOR_TARGETS_WRITE,
    require_permission,
)
from ...services import audit as audit_service
from ...services.entitlements import EntitlementError
from ...tenant_context import TenantContext
from ..models.checks import MonitorCheckCreate, MonitorCheckPatch
from ..services import checks as checks_service
from ..services import live_gates as live_gates_service
from ..services.checks import MonitorChecksError

router = APIRouter(prefix="/checks", tags=["monitor-checks"])


def _raise(exc: MonitorChecksError | EntitlementError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("")
def list_checks(
    protocol: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    target_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_READ)),
) -> dict[str, Any]:
    try:
        return checks_service.list_checks(
            tenant_id=tenant.tenant_id,
            protocol=protocol,
            enabled=enabled,
            target_id=target_id,
            page=page,
            page_size=page_size,
        )
    except MonitorChecksError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("", status_code=201)
def create_check(
    request: Request,
    body: MonitorCheckCreate,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_WRITE)),
) -> dict[str, Any]:
    try:
        doc = checks_service.create_check(
            tenant_id=tenant.tenant_id,
            payload=body.model_dump(),
        )
    except EntitlementError as exc:
        _raise(exc)
        raise  # pragma: no cover
    except MonitorChecksError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.checks.create",
        resource_type="monitor_checks",
        resource_id=doc.get("check_id"),
        details={
            "protocol": doc.get("protocol"),
            "target_id": doc.get("target_id"),
            "enabled": doc.get("enabled"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/{check_id}")
def get_check(
    check_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_READ)),
) -> dict[str, Any]:
    doc = checks_service.get_check(tenant_id=tenant.tenant_id, check_id=check_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Check '{check_id}' not found")
    return doc


@router.patch("/{check_id}")
def patch_check(
    check_id: str,
    request: Request,
    body: MonitorCheckPatch,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_WRITE)),
) -> dict[str, Any]:
    try:
        doc = checks_service.patch_check(
            tenant_id=tenant.tenant_id,
            check_id=check_id,
            payload=body.model_dump(exclude_unset=True),
        )
    except MonitorChecksError as exc:
        _raise(exc)
        raise  # pragma: no cover
    patch_details = body.model_dump(exclude_unset=True)
    audit_service.record_from_tenant(
        tenant,
        action="monitor.checks.update",
        resource_type="monitor_checks",
        resource_id=check_id,
        details={
            k: patch_details[k]
            for k in ("protocol", "enabled", "target_id")
            if k in patch_details
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.delete("/{check_id}", status_code=204)
def delete_check(
    check_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_WRITE)),
) -> None:
    deleted = checks_service.delete_check(
        tenant_id=tenant.tenant_id, check_id=check_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Check '{check_id}' not found")
    audit_service.record_from_tenant(
        tenant,
        action="monitor.checks.delete",
        resource_type="monitor_checks",
        resource_id=check_id,
        details={},
        request_method=request.method,
        request_path=str(request.url.path),
    )


@router.get("/{check_id}/results")
def list_check_results(
    check_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_READ)),
) -> dict[str, Any]:
    try:
        return checks_service.list_check_results(
            tenant_id=tenant.tenant_id,
            check_id=check_id,
            page=page,
            page_size=page_size,
        )
    except MonitorChecksError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/{check_id}/run-once")
def run_check_once(
    check_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_WRITE)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Execute one agentless check (gated + egress allowlist). Writes LIVE rows when allowed."""
    live_gates_service.require_live_capability(
        tenant_id=tenant.tenant_id,
        capability="agentless_poll",
        settings=settings,
    )
    try:
        return checks_service.run_check_once(
            tenant_id=tenant.tenant_id,
            check_id=check_id,
            settings=settings,
        )
    except MonitorChecksError as exc:
        _raise(exc)
        raise  # pragma: no cover
