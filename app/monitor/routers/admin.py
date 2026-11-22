"""Monitoring admin APIs — retention sweeper + cold archive + live settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ...config import Settings, get_settings
from ...permissions import PERM_MONITOR_ADMIN, require_permission
from ...services import audit as audit_service
from ...services import tenants as tenants_service
from ...services.tenants import TenantError
from ...tenant_context import TenantContext
from ..services import cold_storage as cold_storage_service
from ..services import live_gates as live_gates_service
from ..services import poller as poller_service
from ..services import retention as retention_service
from ..services.cold_storage import ColdStorageError

router = APIRouter(prefix="/admin", tags=["monitor-admin"])


class LiveSettingsPatch(BaseModel):
    """Tenant-scoped live opt-in toggles (platform env is not changed here)."""

    model_config = ConfigDict(extra="forbid")

    monitor_live_opt_in: bool | None = None
    monitor_live_agentless_opt_in: bool | None = None
    monitor_live_agent_opt_in: bool | None = None
    monitor_auto_incident_opt_in: bool | None = None
    monitor_retention_tier: str | None = Field(
        default=None, description="hot | extended | siem"
    )


def _live_settings_payload(
    *, tenant_id: str, settings: Settings
) -> dict[str, Any]:
    tenant = live_gates_service.tenant_live_settings(tenant_id)
    gates = live_gates_service.live_gates(tenant_id=tenant_id, settings=settings)
    return {
        "tenant_id": tenant_id,
        "platform": {
            "monitor_live_probes_enabled": bool(settings.monitor_live_probes_enabled),
            "monitor_live_agentless_enabled": bool(
                settings.monitor_live_agentless_enabled
            ),
            "monitor_live_agent_enabled": bool(settings.monitor_live_agent_enabled),
            "monitor_live_http_ingest_enabled": bool(
                settings.monitor_live_http_ingest_enabled
            ),
            "monitor_live_syslog_bind": (settings.monitor_live_syslog_bind or "").strip()
            or None,
            "monitor_poller_enabled": bool(settings.monitor_poller_enabled),
        },
        "tenant": tenant,
        "live_gates": gates,
        "live_probes": bool(gates["platform_enabled"] and gates["tenant_opt_in"]),
    }


@router.post("/retention-sweep")
def retention_sweep(
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
) -> dict[str, Any]:
    """Trim over-age + over-limit metric samples / log events / diagnostics."""
    return retention_service.sweep_tenant_retention(tenant_id=tenant.tenant_id)


@router.post("/cold-archive")
def cold_archive(
    request: Request,
    older_than_days: int | None = Query(
        default=None, ge=1, le=3650, description="Archive events older than N days"
    ),
    limit: int = Query(default=5000, ge=1, le=50_000),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Export aged log events to MONITOR_COLD_STORAGE_URI (file:// first).

    Empty URI → explicit no-op success with reason ``cold storage not configured``.
    Does not delete hot Mongo rows (sweeper owns deletes).
    """
    try:
        result = retention_service.run_cold_archive(
            tenant_id=tenant.tenant_id,
            older_than_days=older_than_days,
            limit=limit,
            settings=settings,
        )
    except ColdStorageError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    audit_service.record_from_tenant(
        tenant,
        action="monitor.admin.cold_archive",
        resource_type="monitor_retention_jobs",
        resource_id=result.get("job_id") or tenant.tenant_id,
        details={
            "archived": result.get("archived"),
            "reason": result.get("reason"),
            "event_count": result.get("event_count"),
            "status": result.get("status"),
            "older_than_days": result.get("older_than_days"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return result


@router.get("/retention-jobs")
def list_retention_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
) -> dict[str, Any]:
    """List recent cold-archive / retention jobs for the tenant."""
    return cold_storage_service.list_retention_jobs(
        tenant_id=tenant.tenant_id, limit=limit
    )


@router.get("/live-settings")
def get_live_settings(
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Platform flag visibility + tenant live opt-in fields."""
    return _live_settings_payload(tenant_id=tenant.tenant_id, settings=settings)


@router.patch("/live-settings")
def patch_live_settings(
    payload: LiveSettingsPatch,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Toggle tenant live opt-in fields (audited). Does not change platform env."""
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No live settings fields provided")
    try:
        tenants_service.set_monitor_live_settings(tenant.tenant_id, updates)
    except TenantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    audit_service.record_from_tenant(
        tenant,
        action="monitor.live_settings.update",
        resource_type="monitor_live_settings",
        resource_id=tenant.tenant_id,
        details=updates,
        request_method="PATCH",
        request_path="/api/monitor/admin/live-settings",
    )
    return _live_settings_payload(tenant_id=tenant.tenant_id, settings=settings)


@router.post("/poller/tick")
def poller_tick(
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Manual poller tick (lab/tests). Forces a tick; still respects per-tenant gates."""
    result = poller_service.run_tick(settings=settings, force=True)
    return {
        **result,
        "caller_tenant_id": tenant.tenant_id,
        "poller_running": poller_service.is_running(),
    }
