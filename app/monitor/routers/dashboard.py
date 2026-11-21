"""Monitoring dashboard aggregates API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...config import Settings, get_settings
from ...permissions import PERM_MONITOR_DASHBOARD_READ, require_permission
from ...tenant_context import TenantContext
from ..services import dashboard as dashboard_service

router = APIRouter(tags=["monitor"])


@router.get("/dashboard")
def get_dashboard(
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_DASHBOARD_READ)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Aggregate health / alerts / log+file volume from monitor collections.

    Requires ``monitor:dashboard:read``. SIMULATED data only — no live probes.
    """
    return dashboard_service.summary(
        tenant_id=tenant.tenant_id,
        settings=settings,
    )
