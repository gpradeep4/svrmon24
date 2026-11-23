"""Service Portal meta API — SIMULATED banner + collect modes (tenant-scoped)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...config import Settings, get_settings
from ...permissions import PERM_SP_CATALOG_READ, require_permission
from ...tenant_context import TenantContext
from ..services import meta as meta_service

router = APIRouter(tags=["portal"])


@router.get("/meta")
def get_meta(
    tenant: TenantContext = Depends(require_permission(PERM_SP_CATALOG_READ)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Module metadata — live_exec false until SP9 gates + user unlock.

    Requires ``sp:catalog:read``.
    """
    payload = meta_service.module_meta(
        settings=settings, tenant_id=tenant.tenant_id
    )
    payload["tenant_id"] = tenant.tenant_id
    return payload
