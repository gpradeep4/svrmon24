"""Approvals Management APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ...permissions import (
    PERM_ITSM_APPROVAL_DECIDE,
    PERM_ITSM_APPROVAL_READ,
    require_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..models.approvals import ApprovalCreate, ApprovalDecide, ApprovalUpdate
from ..services import approvals as approvals_service
from ..services.approvals import ApprovalError

router = APIRouter(prefix="/approvals", tags=["itsm-approvals"])


class ApprovalCancelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str | None = Field(default=None, max_length=4000)


def _raise(exc: ApprovalError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


@router.get("")
def list_approvals(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    ticket_type: str | None = Query(default=None),
    ticket_id: str | None = Query(default=None),
    workflow_execution_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_APPROVAL_READ)),
) -> dict[str, Any]:
    try:
        return approvals_service.list_approvals(
            tenant_id=tenant.tenant_id,
            q=q,
            status=status,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            workflow_execution_id=workflow_execution_id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except ApprovalError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("", status_code=201)
def create_approval(
    payload: ApprovalCreate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_APPROVAL_DECIDE)),
) -> dict[str, Any]:
    try:
        doc = approvals_service.create_approval(
            payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except ApprovalError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.approval.create",
        resource_type="itsm_approval",
        resource_id=doc.get("approval_id"),
        details={
            "ticket_type": doc.get("ticket_type"),
            "ticket_id": doc.get("ticket_id"),
            "status": doc.get("status"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/{approval_id}")
def get_approval(
    approval_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_APPROVAL_READ)),
) -> dict[str, Any]:
    doc = approvals_service.get_approval(approval_id, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Approval '{approval_id}' not found"
        )
    return doc


@router.patch("/{approval_id}")
def update_approval(
    approval_id: str,
    payload: ApprovalUpdate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_APPROVAL_DECIDE)),
) -> dict[str, Any]:
    try:
        doc = approvals_service.update_approval(
            approval_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except ApprovalError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.approval.update",
        resource_type="itsm_approval",
        resource_id=approval_id,
        details=payload.model_dump(exclude_unset=True),
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/{approval_id}/decide")
def decide_approval(
    approval_id: str,
    payload: ApprovalDecide,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_APPROVAL_DECIDE)),
) -> dict[str, Any]:
    try:
        doc = approvals_service.decide_approval(
            approval_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except ApprovalError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.approval.decide",
        resource_type="itsm_approval",
        resource_id=approval_id,
        details={"decision": payload.decision},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/{approval_id}/cancel")
def cancel_approval(
    approval_id: str,
    payload: ApprovalCancelBody,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_APPROVAL_DECIDE)),
) -> dict[str, Any]:
    try:
        doc = approvals_service.cancel_approval(
            approval_id,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
            comment=payload.comment,
        )
    except ApprovalError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.approval.cancel",
        resource_type="itsm_approval",
        resource_id=approval_id,
        details={"comment": payload.comment},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc
