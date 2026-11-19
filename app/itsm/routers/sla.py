"""SLA policies + tracking APIs under ``/api/itsm/sla``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...permissions import (
    PERM_ITSM_SLA_ADMIN,
    PERM_ITSM_SLA_READ,
    require_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..models.sla import SlaPolicyCreate, SlaPolicyUpdate
from ..services import sla as sla_service
from ..services.sla import SlaError

router = APIRouter(prefix="/sla", tags=["itsm-sla"])


def _raise(exc: SlaError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


@router.get("/policies")
def list_policies(
    q: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    applies_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_SLA_READ)),
) -> dict[str, Any]:
    try:
        return sla_service.list_policies(
            tenant_id=tenant.tenant_id,
            q=q,
            active=active,
            applies_to=applies_to,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except SlaError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/policies", status_code=201)
def create_policy(
    payload: SlaPolicyCreate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_SLA_ADMIN)),
) -> dict[str, Any]:
    try:
        doc = sla_service.create_policy(
            payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except SlaError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.sla.policy.create",
        resource_type="itsm_sla_policy",
        resource_id=doc.get("policy_id"),
        details={
            "name": doc.get("name"),
            "applies_to": doc.get("applies_to"),
            "active": doc.get("active"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/policies/{policy_id}")
def get_policy(
    policy_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_SLA_READ)),
) -> dict[str, Any]:
    doc = sla_service.get_policy(policy_id, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"SLA policy '{policy_id}' not found"
        )
    return doc


@router.patch("/policies/{policy_id}")
def update_policy(
    policy_id: str,
    payload: SlaPolicyUpdate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_SLA_ADMIN)),
) -> dict[str, Any]:
    try:
        doc = sla_service.update_policy(
            policy_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except SlaError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.sla.policy.update",
        resource_type="itsm_sla_policy",
        resource_id=policy_id,
        details=payload.model_dump(exclude_unset=True),
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/tracking")
def list_tracking(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    ticket_type: str | None = Query(default=None),
    ticket_id: str | None = Query(default=None),
    policy_id: str | None = Query(default=None),
    metric: str | None = Query(default=None),
    overdue: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="due_at"),
    sort_dir: str = Query(default="asc"),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_SLA_READ)),
) -> dict[str, Any]:
    try:
        return sla_service.list_tracking(
            tenant_id=tenant.tenant_id,
            q=q,
            status=status,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            policy_id=policy_id,
            metric=metric,
            overdue=overdue,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except SlaError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/tracking/{tracking_id}")
def get_tracking(
    tracking_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_SLA_READ)),
) -> dict[str, Any]:
    doc = sla_service.get_tracking(tracking_id, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"SLA tracking '{tracking_id}' not found"
        )
    return doc


@router.get("/summary/{ticket_type}/{ticket_id}")
def ticket_sla_summary(
    ticket_type: str,
    ticket_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_SLA_READ)),
) -> dict[str, Any]:
    try:
        return sla_service.summary_for_ticket(
            tenant_id=tenant.tenant_id,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
        )
    except SlaError as exc:
        _raise(exc)
        raise  # pragma: no cover
