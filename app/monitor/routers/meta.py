"""Monitoring meta API — SIMULATED banner + DB name (tenant-scoped)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...config import Settings, get_settings
from ...tenant_context import TenantContext, require_tenant
from ..services import meta as meta_service

router = APIRouter(tags=["monitor"])


@router.get("/meta")
def get_meta(
    tenant: TenantContext = Depends(require_tenant),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Module metadata — always SIMULATED; no live probes."""
    payload = meta_service.module_meta(settings=settings)
    payload["tenant_id"] = tenant.tenant_id
    return payload
