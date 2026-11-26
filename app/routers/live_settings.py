"""Unified admin live / runtime settings — Configuration → Live / Runtime."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings, get_settings
from ..permissions import PERM_LIVE_ADMIN, require_permission
from ..services import audit as audit_service
from ..services import live_settings as live_settings_service
from ..services.tenants import TenantError
from ..tenant_context import TenantContext

router = APIRouter(prefix="/api/admin", tags=["admin-live-settings"])


class UnifiedLiveSettingsPatch(BaseModel):
    """Tenant-scoped live opt-in toggles (platform env is never changed here)."""

    model_config = ConfigDict(extra="forbid")

    monitor_live_opt_in: bool | None = None
    monitor_live_agentless_opt_in: bool | None = None
    monitor_live_agent_opt_in: bool | None = None
    monitor_auto_incident_opt_in: bool | None = None
    monitor_retention_tier: str | None = Field(
        default=None, description="hot | extended | siem"
    )
    sp_live_opt_in: bool | None = None
    sp_live_agentless_opt_in: bool | None = None
    sp_live_agent_opt_in: bool | None = None
    diagnostics_live_opt_in: bool | None = None
    itsm_automation_opt_in: bool | None = None


@router.get("/live-settings")
def get_live_settings(
    tenant: TenantContext = Depends(require_permission(PERM_LIVE_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Platform flag visibility + all tenant live opt-in fields (admin only)."""
    payload = live_settings_service.unified_live_settings(
        tenant_id=tenant.tenant_id, settings=settings
    )
    payload["can_write"] = True
    return payload


@router.patch("/live-settings")
def patch_live_settings(
    payload: UnifiedLiveSettingsPatch,
    tenant: TenantContext = Depends(require_permission(PERM_LIVE_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Toggle tenant live opt-in fields across modules (audited)."""
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No live settings fields provided")
    try:
        result = live_settings_service.apply_unified_live_settings(
            tenant.tenant_id, updates
        )
    except TenantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    audit_service.record_from_tenant(
        tenant,
        action="admin.live_settings.update",
        resource_type="live_settings",
        resource_id=tenant.tenant_id,
        details=updates,
        request_method="PATCH",
        request_path="/api/admin/live-settings",
    )
    # Refresh with current settings (env masters unchanged).
    out = live_settings_service.unified_live_settings(
        tenant_id=tenant.tenant_id, settings=settings
    )
    out["can_write"] = True
    out["updated_fields"] = sorted(updates.keys())
    # Keep apply result modules if settings cache identical.
    if result.get("modules"):
        out["modules"] = result["modules"]
    return out
