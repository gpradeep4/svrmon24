"""Audit event APIs (Master Phase 14).

List/get are tenant-scoped. Tenant admin of the current org, or platform
admin, may read. Cross-tenant access returns 404.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import require_user
from ..services import audit as audit_service
from ..services.audit import AuditError
from ..tenancy import MEMBERSHIP_ROLE_ADMIN
from ..tenant_context import TenantContext, require_tenant

router = APIRouter(
    prefix="/api/audit-events",
    tags=["audit"],
    dependencies=[Depends(require_user)],
)


def _require_audit_reader(tenant_ctx: TenantContext) -> None:
    if tenant_ctx.is_platform_admin:
        return
    if tenant_ctx.membership_role == MEMBERSHIP_ROLE_ADMIN:
        return
    # Basic sessions have no membership_role — allow Basic migration-tenant
    # operators to inspect audit during cutover (still tenant-scoped).
    if tenant_ctx.auth_user.auth_method == "basic":
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Tenant admin, platform admin, or Basic migration session required",
    )


def _raise(exc: AuditError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("")
def list_audit_events(
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    _require_audit_reader(tenant)
    try:
        return audit_service.list_events(
            tenant_id=tenant.tenant_id,
            action=action,
            resource_type=resource_type,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover — surfaced as 503 when Mongo down
        from ..db import DatabaseUnavailableError

        if isinstance(exc, DatabaseUnavailableError):
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise


@router.get("/{audit_id}")
def get_audit_event(
    audit_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    _require_audit_reader(tenant)
    doc = audit_service.get_event(audit_id, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit event '{audit_id}' not found",
        )
    return doc
