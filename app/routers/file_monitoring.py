"""File Monitoring APIs — SIMULATED / demo only (tenant-scoped)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_user
from ..permissions import PERM_FILE_MONITORING_READ, require_permission
from ..services import file_monitoring as file_monitoring_service
from ..services.file_monitoring import FileMonitoringError
from ..tenant_context import TenantContext

router = APIRouter(
    prefix="/api/file-monitoring",
    tags=["file-monitoring"],
    dependencies=[Depends(require_user)],
)


def _raise(exc: FileMonitoringError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/meta")
def get_meta(
    tenant: TenantContext = Depends(require_permission(PERM_FILE_MONITORING_READ)),
) -> dict[str, Any]:
    """Module metadata — always SIMULATED; no live watching."""
    meta = file_monitoring_service.module_meta()
    meta["tenant_id"] = tenant.tenant_id
    return meta


@router.get("/targets")
def list_targets(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_FILE_MONITORING_READ)),
) -> dict[str, Any]:
    return file_monitoring_service.list_targets(
        tenant_id=tenant.tenant_id,
        q=q,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/targets/{watch_id}")
def get_target(
    watch_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_FILE_MONITORING_READ)),
) -> dict[str, Any]:
    doc = file_monitoring_service.get_target(
        tenant_id=tenant.tenant_id, watch_id=watch_id
    )
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Watch target '{watch_id}' not found"
        )
    return doc


@router.get("/targets/{watch_id}/versions")
def list_versions(
    watch_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_FILE_MONITORING_READ)),
) -> dict[str, Any]:
    try:
        return file_monitoring_service.list_versions(
            tenant_id=tenant.tenant_id,
            watch_id=watch_id,
            page=page,
            page_size=page_size,
        )
    except FileMonitoringError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/versions/{event_id}")
def get_version_event(
    event_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_FILE_MONITORING_READ)),
) -> dict[str, Any]:
    doc = file_monitoring_service.get_version_event(
        tenant_id=tenant.tenant_id, event_id=event_id
    )
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Version event '{event_id}' not found"
        )
    return doc
