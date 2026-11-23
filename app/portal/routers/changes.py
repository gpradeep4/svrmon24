"""Service Portal Change-status APIs (ITSM Change is approval SoT)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...permissions import (
    PERM_SP_APPROVAL_READ,
    PERM_SP_REQUEST_READ,
    assert_any_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext, require_tenant
from ..services import approvals as approvals_service
from ..services.approvals import ApprovalError

router = APIRouter(prefix="/changes", tags=["portal-changes"])


def _raise(exc: ApprovalError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


def _require_change_status_read(
    tenant: TenantContext = Depends(require_tenant),
) -> TenantContext:
    assert_any_permission(
        tenant, (PERM_SP_APPROVAL_READ, PERM_SP_REQUEST_READ)
    )
    return tenant


@router.get("")
def list_change_status(
    status: str | None = Query(default=None),
    change_status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(_require_change_status_read),
) -> dict[str, Any]:
    """Portal Change-status view — mirror only; decide in ITSM."""
    try:
        return approvals_service.list_change_status(
            tenant_id=tenant.tenant_id,
            status=status,
            change_status=change_status,
            page=page,
            page_size=page_size,
        )
    except ApprovalError as exc:
        _raise(exc)
    return {}


@router.post("/sync")
def sync_change_statuses(
    limit: int = Query(default=100, ge=1, le=500),
    tenant: TenantContext = Depends(_require_change_status_read),
) -> dict[str, Any]:
    """Batch-sync linked Change statuses onto portal requests."""
    try:
        result = approvals_service.sync_pending_requests(
            tenant_id=tenant.tenant_id, actor=_actor(tenant), limit=limit
        )
    except ApprovalError as exc:
        _raise(exc)
        return {}
    audit_service.record_event(
        tenant_id=tenant.tenant_id,
        action="portal.change.sync",
        resource_type="sp_request",
        resource_id="batch",
        actor=_actor(tenant),
        details={
            "synced": result.get("synced"),
            "transitioned": result.get("transitioned"),
            "errors": len(result.get("errors") or []),
        },
    )
    return result


@router.post("/{request_id}/sync")
def sync_one_change_status(
    request_id: str,
    tenant: TenantContext = Depends(_require_change_status_read),
) -> dict[str, Any]:
    try:
        doc = approvals_service.sync_request_from_change(
            request_id, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except ApprovalError as exc:
        _raise(exc)
        return {}
    audit_service.record_event(
        tenant_id=tenant.tenant_id,
        action="portal.change.sync",
        resource_type="sp_request",
        resource_id=request_id,
        actor=_actor(tenant),
        details={
            "change_id": doc.get("change_id"),
            "status": doc.get("status"),
            "change_status_snapshot": doc.get("change_status_snapshot"),
        },
    )
    return doc
