"""Change Management APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ...permissions import PERM_ITSM_CHANGE_READ, PERM_ITSM_CHANGE_WRITE, require_permission
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..models.changes import (
    ChangeCiLinkCreate,
    ChangeCreate,
    ChangeTransition,
    ChangeUpdate,
)
from ..services import ai_risk_assist as ai_risk_assist_service
from ..services import changes as changes_service
from ..services.changes import ChangeError

router = APIRouter(prefix="/changes", tags=["itsm-changes"])


def _raise(exc: ChangeError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


class ChangeAiRequest(BaseModel):
    force_fallback: bool = Field(default=False)


@router.get("")
def list_changes(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    change_type: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    assignee_user_id: str | None = Query(default=None),
    component_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_CHANGE_READ)),
) -> dict[str, Any]:
    try:
        return changes_service.list_changes(
            tenant_id=tenant.tenant_id,
            q=q,
            status=status,
            change_type=change_type,
            priority=priority,
            assignee_user_id=assignee_user_id,
            component_id=component_id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except ChangeError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("", status_code=201)
def create_change(
    payload: ChangeCreate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_CHANGE_WRITE)),
) -> dict[str, Any]:
    try:
        doc = changes_service.create_change(
            payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except ChangeError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.change.create",
        resource_type="itsm_change",
        resource_id=doc.get("change_id"),
        details={"number": doc.get("number"), "status": doc.get("status")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/{change_id}")
def get_change(
    change_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_CHANGE_READ)),
) -> dict[str, Any]:
    doc = changes_service.get_change(change_id, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Change '{change_id}' not found")
    return doc


@router.post("/{change_id}/ai/risk")
def change_ai_risk(
    change_id: str,
    payload: ChangeAiRequest | None = None,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_CHANGE_READ)),
) -> dict[str, Any]:
    """Assist-only change risk narrative. Never auto-approves CAB."""
    try:
        return ai_risk_assist_service.suggest_change_risk(
            change_id,
            tenant_id=tenant.tenant_id,
            force_fallback=bool(payload.force_fallback) if payload else False,
        )
    except ChangeError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.patch("/{change_id}")
def update_change(
    change_id: str,
    payload: ChangeUpdate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_CHANGE_WRITE)),
) -> dict[str, Any]:
    try:
        doc = changes_service.update_change(
            change_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except ChangeError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.change.update",
        resource_type="itsm_change",
        resource_id=change_id,
        details=payload.model_dump(exclude_unset=True),
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/{change_id}/transition")
def transition_change(
    change_id: str,
    payload: ChangeTransition,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_CHANGE_WRITE)),
) -> dict[str, Any]:
    try:
        doc = changes_service.transition_change(
            change_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except ChangeError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.change.transition",
        resource_type="itsm_change",
        resource_id=change_id,
        details={"status": payload.status},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/{change_id}/ci-links", status_code=201)
def add_ci_link(
    change_id: str,
    payload: ChangeCiLinkCreate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_CHANGE_WRITE)),
) -> dict[str, Any]:
    try:
        doc = changes_service.add_ci_link(
            change_id,
            component_id=payload.component_id,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except ChangeError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.change.ci_link_add",
        resource_type="itsm_change",
        resource_id=change_id,
        details={"component_id": payload.component_id},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.delete("/{change_id}/ci-links/{component_id}")
def remove_ci_link(
    change_id: str,
    component_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_CHANGE_WRITE)),
) -> dict[str, Any]:
    try:
        doc = changes_service.remove_ci_link(
            change_id,
            component_id=component_id,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except ChangeError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.change.ci_link_remove",
        resource_type="itsm_change",
        resource_id=change_id,
        details={"component_id": component_id},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc
