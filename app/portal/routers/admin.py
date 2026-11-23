"""Service Portal admin live-settings (SP9 gates; SP10 adapters unlocked)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from ...config import Settings, get_settings
from ...permissions import PERM_SP_ADMIN, require_permission
from ...services import audit as audit_service
from ...services import tenants as tenants_service
from ...services.tenants import TenantError
from ...tenant_context import TenantContext
from ..services import live_gates as live_gates_service

router = APIRouter(prefix="/admin", tags=["portal-admin"])


class LiveSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sp_live_opt_in: bool | None = None
    sp_live_agentless_opt_in: bool | None = None
    sp_live_agent_opt_in: bool | None = None


def _live_settings_payload(
    *, tenant_id: str, settings: Settings
) -> dict[str, Any]:
    tenant = live_gates_service.tenant_live_settings(tenant_id)
    gates = live_gates_service.live_gates(tenant_id=tenant_id, settings=settings)
    return {
        "platform": {
            "SERVICE_PORTAL_LIVE_EXEC_ENABLED": bool(
                settings.service_portal_live_exec_enabled
            ),
            "SERVICE_PORTAL_LIVE_AGENTLESS_ENABLED": bool(
                settings.service_portal_live_agentless_enabled
            ),
            "SERVICE_PORTAL_LIVE_AGENT_ENABLED": bool(
                settings.service_portal_live_agent_enabled
            ),
            "SERVICE_PORTAL_EGRESS_ALLOWLIST_SET": bool(
                (settings.service_portal_egress_allowlist or "").strip()
            ),
        },
        "tenant": tenant,
        "effective": gates,
        "live_adapters": True,
        "cloud_provision": "terraform",
        "note": (
            "LIVE adapters are unlocked (SP10). Platform "
            "SERVICE_PORTAL_LIVE_EXEC_ENABLED and tenant sp_live_opt_in must "
            "both be on; agentless/agent sub-gates still apply. Cloud VM "
            "provision uses Terraform. DRY_RUN remains plan-only."
        ),
    }


@router.get("/live-settings")
def get_live_settings(
    tenant: TenantContext = Depends(require_permission(PERM_SP_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return _live_settings_payload(tenant_id=tenant.tenant_id, settings=settings)


@router.patch("/live-settings")
def patch_live_settings(
    payload: LiveSettingsPatch,
    tenant: TenantContext = Depends(require_permission(PERM_SP_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No live settings fields provided")
    try:
        tenants_service.set_portal_live_settings(tenant.tenant_id, updates)
    except TenantError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    audit_service.record_from_tenant(
        tenant,
        action="portal.live_settings.update",
        resource_type="sp_live_settings",
        resource_id=tenant.tenant_id,
        details=updates,
        request_method="PATCH",
        request_path="/api/portal/admin/live-settings",
    )
    from ..services import audit as portal_audit

    portal_audit.record_portal_event(
        tenant_id=tenant.tenant_id,
        action="portal.live_settings.update",
        actor=audit_service.actor_from_tenant(tenant),
        resource_type="sp_live_settings",
        resource_id=tenant.tenant_id,
        details=updates,
    )
    return _live_settings_payload(tenant_id=tenant.tenant_id, settings=settings)
