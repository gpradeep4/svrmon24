"""Ticket activity timeline APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from ...permissions import (
    PERM_ITSM_INCIDENT_READ,
    PERM_ITSM_INCIDENT_WRITE,
    assert_permission,
    require_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext, require_tenant
from ..models.common import TicketActivityCreate
from ..services import activities as activities_service
from ..services import incidents as incidents_service
from ..services.activities import ActivityError

router = APIRouter(tags=["itsm-activities"])


def _ensure_ticket_exists(ticket_type: str, ticket_id: str, *, tenant_id: str) -> None:
    if ticket_type != "incident":
        raise HTTPException(
            status_code=400,
            detail="Only ticket_type=incident is supported in this slice",
        )
    doc = incidents_service.get_incident(ticket_id, tenant_id=tenant_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Incident '{ticket_id}' not found"
        )


@router.get("/{ticket_type}/{ticket_id}/activities")
def list_activities(
    ticket_id: str,
    ticket_type: str = Path(pattern="^(incident|change|problem)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_INCIDENT_READ)),
) -> dict[str, Any]:
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
    assert_permission(tenant, PERM_ITSM_INCIDENT_WRITE)
    _ensure_ticket_exists(ticket_type, ticket_id, tenant_id=tenant.tenant_id)
    if payload.activity_type not in {"comment", "system"}:
        # Clients may only post comments; lifecycle events are service-owned.
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
