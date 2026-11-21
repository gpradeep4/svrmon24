"""Monitoring admin APIs — retention sweeper (SIMULATED; no live probes)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...permissions import PERM_MONITOR_ADMIN, require_permission
from ...tenant_context import TenantContext
from ..services import retention as retention_service

router = APIRouter(prefix="/admin", tags=["monitor-admin"])


@router.post("/retention-sweep")
def retention_sweep(
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
) -> dict[str, Any]:
    """Trim over-limit metric samples / log events / diagnostics for the tenant."""
    return retention_service.sweep_tenant_retention(tenant_id=tenant.tenant_id)
