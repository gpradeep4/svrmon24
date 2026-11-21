"""Incident Management APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ...permissions import PERM_ITSM_INCIDENT_READ, PERM_ITSM_INCIDENT_WRITE, require_permission
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..models.incidents import (
    IncidentCiLinkCreate,
    IncidentCreate,
    IncidentTransition,
    IncidentUpdate,
)
from ..services import ai_assist as ai_assist_service
from ..services import incidents as incidents_service
from ..services.incidents import IncidentError

router = APIRouter(prefix="/incidents", tags=["itsm-incidents"])


def _raise(exc: IncidentError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


class IncidentAiRequest(BaseModel):
    force_fallback: bool = Field(default=False)


@router.get("")
def list_incidents(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    assignee_user_id: str | None = Query(default=None),
    component_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_INCIDENT_READ)),
) -> dict[str, Any]:
    try:
        return incidents_service.list_incidents(
            tenant_id=tenant.tenant_id,
            q=q,
            status=status,
            priority=priority,
            assignee_user_id=assignee_user_id,
            component_id=component_id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except IncidentError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("", status_code=201)
def create_incident(
    payload: IncidentCreate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_INCIDENT_WRITE)),
) -> dict[str, Any]:
    try:
        doc = incidents_service.create_incident(
            payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except IncidentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.incident.create",
        resource_type="itsm_incident",
        resource_id=doc.get("incident_id"),
        details={"number": doc.get("number"), "status": doc.get("status")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/{incident_id}")
def get_incident(
    incident_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_INCIDENT_READ)),
) -> dict[str, Any]:
    doc = incidents_service.get_incident(incident_id, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Incident '{incident_id}' not found"
        )
    return doc


@router.post("/{incident_id}/ai/triage")
def incident_ai_triage(
    incident_id: str,
    payload: IncidentAiRequest | None = None,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_INCIDENT_READ)),
) -> dict[str, Any]:
    """Assist-only triage suggestion. Does not write — Apply via PATCH."""
    try:
        return ai_assist_service.suggest_incident_triage(
            incident_id,
            tenant_id=tenant.tenant_id,
            force_fallback=bool(payload.force_fallback) if payload else False,
        )
    except IncidentError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/{incident_id}/ai/summarize")
def incident_ai_summarize(
    incident_id: str,
    payload: IncidentAiRequest | None = None,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_INCIDENT_READ)),
) -> dict[str, Any]:
    """Assist-only summary / resolution draft. Never auto-transitions."""
    try:
        return ai_assist_service.summarize_incident(
            incident_id,
            tenant_id=tenant.tenant_id,
            force_fallback=bool(payload.force_fallback) if payload else False,
        )
    except IncidentError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/{incident_id}/ai/similar")
def incident_ai_similar(
    incident_id: str,
    payload: IncidentAiRequest | None = None,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_INCIDENT_READ)),
) -> dict[str, Any]:
    """Assist-only similar tickets + KB. Never auto-links."""
    try:
        return ai_assist_service.suggest_similar_and_kb(
            incident_id,
            tenant_id=tenant.tenant_id,
            force_fallback=bool(payload.force_fallback) if payload else False,
        )
    except IncidentError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.patch("/{incident_id}")
def update_incident(
    incident_id: str,
    payload: IncidentUpdate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_INCIDENT_WRITE)),
) -> dict[str, Any]:
    try:
        doc = incidents_service.update_incident(
            incident_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except IncidentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.incident.update",
        resource_type="itsm_incident",
        resource_id=incident_id,
        details=payload.model_dump(exclude_unset=True),
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/{incident_id}/transition")
def transition_incident(
    incident_id: str,
    payload: IncidentTransition,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_INCIDENT_WRITE)),
) -> dict[str, Any]:
    try:
        doc = incidents_service.transition_incident(
            incident_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except IncidentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.incident.transition",
        resource_type="itsm_incident",
        resource_id=incident_id,
        details={"status": payload.status},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/{incident_id}/ci-links", status_code=201)
def add_ci_link(
    incident_id: str,
    payload: IncidentCiLinkCreate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_INCIDENT_WRITE)),
) -> dict[str, Any]:
    try:
        doc = incidents_service.add_ci_link(
            incident_id,
            component_id=payload.component_id,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except IncidentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.incident.ci_link_add",
        resource_type="itsm_incident",
        resource_id=incident_id,
        details={"component_id": payload.component_id},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.delete("/{incident_id}/ci-links/{component_id}")
def remove_ci_link(
    incident_id: str,
    component_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_INCIDENT_WRITE)),
) -> dict[str, Any]:
    try:
        doc = incidents_service.remove_ci_link(
            incident_id,
            component_id=component_id,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except IncidentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.incident.ci_link_remove",
        resource_type="itsm_incident",
        resource_id=incident_id,
        details={"component_id": component_id},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc
