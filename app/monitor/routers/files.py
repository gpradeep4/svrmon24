"""File Monitoring live watches API — ``/api/monitor/files`` (L6).

Compat ``/api/file-monitoring`` remains for SIMULATED list/history.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...permissions import (
    PERM_FILE_MONITORING_READ,
    PERM_MONITOR_ADMIN,
    PERM_MONITOR_FILES_READ,
    PERM_MONITOR_TARGETS_WRITE,
    assert_any_permission,
    require_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext, require_tenant
from ..models.file_monitoring import FileWatchPatch
from ..services import file_monitoring as file_service
from ..services.file_monitoring import FileMonitoringError

router = APIRouter(prefix="/files", tags=["monitor-files"])


def _require_files_read(
    tenant: TenantContext = Depends(require_tenant),
) -> TenantContext:
    assert_any_permission(
        tenant, (PERM_MONITOR_FILES_READ, PERM_FILE_MONITORING_READ)
    )
    return tenant


def _require_files_write(
    tenant: TenantContext = Depends(require_tenant),
) -> TenantContext:
    assert_any_permission(
        tenant, (PERM_MONITOR_TARGETS_WRITE, PERM_MONITOR_ADMIN)
    )
    # Also need files read surface for operators configuring watches.
    assert_any_permission(
        tenant, (PERM_MONITOR_FILES_READ, PERM_FILE_MONITORING_READ)
    )
    return tenant


def _raise(exc: FileMonitoringError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/watches")
def list_watches(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    tenant: TenantContext = Depends(_require_files_read),
) -> dict[str, Any]:
    return file_service.list_targets(
        tenant_id=tenant.tenant_id,
        q=q,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/watches/{watch_id}")
def get_watch(
    watch_id: str,
    tenant: TenantContext = Depends(_require_files_read),
) -> dict[str, Any]:
    doc = file_service.get_target(
        tenant_id=tenant.tenant_id, watch_id=watch_id
    )
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Watch target '{watch_id}' not found"
        )
    return doc


@router.patch("/watches/{watch_id}")
def patch_watch(
    watch_id: str,
    body: FileWatchPatch,
    request: Request,
    tenant: TenantContext = Depends(_require_files_write),
) -> dict[str, Any]:
    try:
        doc = file_service.patch_watch(
            tenant_id=tenant.tenant_id,
            watch_id=watch_id,
            payload=body.model_dump(exclude_unset=True),
        )
    except FileMonitoringError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.files.watch.update",
        resource_type="file_watch_targets",
        resource_id=watch_id,
        details={
            "watch_mode": doc.get("watch_mode"),
            "agent_id": doc.get("agent_id"),
            "execution_mode": doc.get("execution_mode"),
            "poll_url_set": bool(doc.get("poll_url")),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/watches/{watch_id}/versions")
def list_watch_versions(
    watch_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(_require_files_read),
) -> dict[str, Any]:
    try:
        return file_service.list_versions(
            tenant_id=tenant.tenant_id,
            watch_id=watch_id,
            page=page,
            page_size=page_size,
        )
    except FileMonitoringError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/watches/{watch_id}/poll-once")
def poll_watch_once(
    watch_id: str,
    request: Request,
    force: bool = Query(default=False),
    tenant: TenantContext = Depends(
        require_permission(PERM_MONITOR_TARGETS_WRITE)
    ),
) -> dict[str, Any]:
    """Manual AGENTLESS_POLL checksum tick (lab / tests)."""
    try:
        result = file_service.poll_watch_once(
            tenant_id=tenant.tenant_id,
            watch_id=watch_id,
            force=force,
        )
    except FileMonitoringError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.files.watch.poll_once",
        resource_type="file_watch_targets",
        resource_id=watch_id,
        details={
            "changed": result.get("changed"),
            "ok": result.get("ok"),
            "denied": result.get("denied"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return result
