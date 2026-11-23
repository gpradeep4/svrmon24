"""Service Portal audit list API (SP7)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ...permissions import PERM_SP_ADMIN, PERM_SP_REQUEST_READ, assert_any_permission
from ...tenant_context import TenantContext, require_tenant
from ..services import audit as portal_audit

router = APIRouter(prefix="/audit", tags=["portal-audit"])


def _require_audit_read(
    tenant: TenantContext = Depends(require_tenant),
) -> TenantContext:
    assert_any_permission(tenant, (PERM_SP_ADMIN, PERM_SP_REQUEST_READ))
    return tenant


@router.get("")
def list_portal_audit(
    action: str | None = Query(default=None),
    request_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(_require_audit_read),
) -> dict[str, Any]:
    return portal_audit.list_portal_events(
        tenant_id=tenant.tenant_id,
        action=action,
        request_id=request_id,
        page=page,
        page_size=page_size,
    )
