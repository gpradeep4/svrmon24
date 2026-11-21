"""Assignment group directory APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...permissions import (
    PERM_ITSM_GROUPS_ADMIN,
    PERM_ITSM_GROUPS_READ,
    require_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..models.assignment_groups import AssignmentGroupCreate, AssignmentGroupUpdate
from ..services import assignment_groups as groups_service
from ..services.assignment_groups import AssignmentGroupError

router = APIRouter(prefix="/assignment-groups", tags=["itsm-assignment-groups"])


def _raise(exc: AssignmentGroupError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


@router.get("")
def list_assignment_groups(
    q: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_GROUPS_READ)),
) -> dict[str, Any]:
    return groups_service.list_groups(
        tenant_id=tenant.tenant_id,
        q=q,
        active=active,
        page=page,
        page_size=page_size,
    )


@router.get("/picker")
def assignment_group_picker(
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_GROUPS_READ)),
) -> dict[str, Any]:
    names = groups_service.picker_names(tenant_id=tenant.tenant_id, active_only=True)
    return {"items": names, "tenant_id": tenant.tenant_id}


@router.get("/{group_id}")
def get_assignment_group(
    group_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_GROUPS_READ)),
) -> dict[str, Any]:
    doc = groups_service.get_group(group_id, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Assignment group '{group_id}' not found")
    return doc


@router.post("", status_code=201)
def create_assignment_group(
    payload: AssignmentGroupCreate,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_GROUPS_ADMIN)),
) -> dict[str, Any]:
    try:
        return groups_service.create_group(
            payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except AssignmentGroupError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.patch("/{group_id}")
def update_assignment_group(
    group_id: str,
    payload: AssignmentGroupUpdate,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_GROUPS_ADMIN)),
) -> dict[str, Any]:
    try:
        return groups_service.update_group(
            group_id, payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except AssignmentGroupError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.delete("/{group_id}")
def delete_assignment_group(
    group_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_GROUPS_ADMIN)),
) -> dict[str, Any]:
    try:
        return groups_service.delete_group(group_id, tenant_id=tenant.tenant_id)
    except AssignmentGroupError as exc:
        _raise(exc)
        raise  # pragma: no cover
