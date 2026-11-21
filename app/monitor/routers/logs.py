"""Monitoring log streams + events API (SIMULATED)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...permissions import (
    PERM_MONITOR_ADMIN,
    PERM_MONITOR_LOGS_READ,
    require_permission,
)
from ...services import audit as audit_service
from ...services.entitlements import EntitlementError
from ...tenant_context import TenantContext
from ..services import logs as logs_service
from ..services.logs import MonitorLogsError

router = APIRouter(prefix="/logs", tags=["monitor-logs"])


def _raise(exc: MonitorLogsError | EntitlementError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/streams")
def list_streams(
    q: str | None = Query(default=None),
    component_id: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    collect_mode: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_LOGS_READ)),
) -> dict[str, Any]:
    try:
        return logs_service.list_streams(
            tenant_id=tenant.tenant_id,
            q=q,
            component_id=component_id,
            source_kind=source_kind,
            status=status,
            collect_mode=collect_mode,
            page=page,
            page_size=page_size,
        )
    except MonitorLogsError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/events")
def list_events(
    q: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    stream_id: str | None = Query(default=None),
    component_id: str | None = Query(default=None),
    source: str | None = Query(default=None),
    collect_mode: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_dir: str = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_LOGS_READ)),
) -> dict[str, Any]:
    try:
        return logs_service.list_events(
            tenant_id=tenant.tenant_id,
            q=q,
            severity=severity,
            stream_id=stream_id,
            component_id=component_id,
            source=source,
            collect_mode=collect_mode,
            page=page,
            page_size=page_size,
            sort_dir=sort_dir,
        )
    except MonitorLogsError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/simulate-tick")
def simulate_tick(
    request: Request,
    events_per_stream: int = Query(default=3, ge=1, le=20),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
) -> dict[str, Any]:
    """Admin-only SIMULATED demo writer (no live syslog ingest)."""
    try:
        result = logs_service.simulate_tick(
            tenant_id=tenant.tenant_id,
            events_per_stream=events_per_stream,
        )
    except EntitlementError as exc:
        _raise(exc)
        raise  # pragma: no cover
    except MonitorLogsError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.logs.simulate_tick",
        resource_type="log_events",
        resource_id=tenant.tenant_id,
        details={
            "events_created": result.get("events_created"),
            "events_trimmed": result.get("events_trimmed"),
            "streams_ensured": result.get("streams_ensured"),
            "ticks_today": result.get("ticks_today"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return result
