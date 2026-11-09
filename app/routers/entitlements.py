"""Entitlements API — plan limits only (no payment provider)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..auth import require_user
from ..services import entitlements as entitlements_service
from ..tenant_context import TenantContext, require_tenant

router = APIRouter(
    prefix="/api/entitlements",
    tags=["entitlements"],
    dependencies=[Depends(require_user)],
)


@router.get("")
def get_entitlements(
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Current tenant plan limits (entitlements-only; billing_enabled=false)."""
    return entitlements_service.get_tenant_entitlements(tenant.tenant_id)


@router.get("/plans")
def list_plans() -> dict[str, Any]:
    """Entitlements plan catalog (no payment / checkout fields)."""
    plans = entitlements_service.list_plans()
    return {
        "items": plans,
        "count": len(plans),
        "billing_enabled": False,
        "payment_provider": None,
        "notes": (
            "Plans are entitlements configuration only. Assign plan_code on a "
            "tenant via platform-admin CLI/API. No payment provider is wired."
        ),
    }
