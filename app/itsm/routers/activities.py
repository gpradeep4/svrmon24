"""Ticket activity timeline APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from ...permissions import (
    PERM_ITSM_CHANGE_READ,
    PERM_ITSM_CHANGE_WRITE,
    PERM_ITSM_INCIDENT_READ,
    PERM_ITSM_INCIDENT_WRITE,
    PERM_ITSM_PROBLEM_READ,
    PERM_ITSM_PROBLEM_WRITE,
    assert_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext, require_tenant
from ..models.common import TicketActivityCreate
from ..services import activities as activities_service
from ..services import changes as changes_service
from ..services import incidents as incidents_service
from ..services import problems as problems_service
from ..services.activities import ActivityError

router = APIRouter(tags=["itsm-activities"])

_READ_PERM = {
    "incident": PERM_ITSM_INCIDENT_READ,
    "change": PERM_ITSM_CHANGE_READ,
    "problem": PERM_ITSM_PROBLEM_READ,
}
_WRITE_PERM = {
    "incident": PERM_ITSM_INCIDENT_WRITE,
    "change": PERM_ITSM_CHANGE_WRITE,
    "problem": PERM_ITSM_PROBLEM_WRITE,
}


def _ensure_ticket_exists(ticket_type: str, ticket_id: str, *, tenant_id: str) -> None:
    if ticket_type == "incident":
        doc = incidents_service.get_incident(ticket_id, tenant_id=tenant_id)
        label = "Incident"
    elif ticket_type == "change":
        doc = changes_service.get_change(ticket_id, tenant_id=tenant_id)
        label = "Change"
    elif ticket_type == "problem":
        doc = problems_service.get_problem(ticket_id, tenant_id=tenant_id)
        label = "Problem"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported ticket_type '{ticket_type}'")
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"{label} '{ticket_id}' not found"
        )


@router.get("/{ticket_type}/{ticket_id}/activities")
def list_activities(
    ticket_id: str,
    ticket_type: str = Path(pattern="^(incident|change|problem)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    assert_permission(tenant, _READ_PERM[ticket_type])
    _ensure_ticket_exists(ticket_type, ticket_id, tenant_id=tenant.tenant_id)
    return activities_service.list_activities(
        tenant_id=tenant.tenant_id,
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        page=page,
        page_size=page_size,
    )


@router.post("/{ticket_type}/{ticket_id}/activities", status_code=201)
def create_activity(
    ticket_id: str,
    payload: TicketActivityCreate,
    request: Request,
    ticket_type: str = Path(pattern="^(incident|change|problem)$"),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    assert_permission(tenant, _WRITE_PERM[ticket_type])
    _ensure_ticket_exists(ticket_type, ticket_id, tenant_id=tenant.tenant_id)
    if payload.activity_type not in {"comment", "system"}:
        if payload.activity_type != "comment":
            raise HTTPException(
                status_code=400,
                detail="Only activity_type=comment is accepted via this endpoint",
            )
    try:
        actor = audit_service.actor_from_tenant(tenant)
        doc = activities_service.append_activity(
            tenant_id=tenant.tenant_id,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            activity_type="comment",
            message=payload.message,
            actor_user_id=actor.get("user_id") or actor.get("username"),
            actor_username=actor.get("username"),
            visibility=payload.visibility,
        )
    except ActivityError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    audit_service.record_from_tenant(
        tenant,
        action="itsm.activity.create",
        resource_type="itsm_ticket_activity",
        resource_id=doc.get("activity_id"),
        details={"ticket_type": ticket_type, "ticket_id": ticket_id},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc
