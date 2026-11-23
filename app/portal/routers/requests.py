"""Service Portal request APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ...permissions import (
    PERM_SP_REQUEST_CANCEL,
    PERM_SP_REQUEST_CREATE,
    PERM_SP_REQUEST_READ,
    require_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..models.requests import RequestCreate, RequestUpdate
from ..services import requests as requests_service
from ..services.requests import RequestError

router = APIRouter(prefix="/requests", tags=["portal-requests"])


def _raise(exc: RequestError) -> None:
    detail: Any = exc.message
    if exc.field_errors:
        detail = {"message": exc.message, "field_errors": exc.field_errors}
    raise HTTPException(status_code=exc.status_code, detail=detail) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


class CancelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str | None = Field(default=None, max_length=2000)


class LinkIncidentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    linked_incident_id: str = Field(min_length=1, max_length=64)


@router.get("")
def list_requests(
    status: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    created_by: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_SP_REQUEST_READ)),
) -> dict[str, Any]:
    try:
        return requests_service.list_requests(
            tenant_id=tenant.tenant_id,
            status=status,
            domain=domain,
            created_by=created_by,
            page=page,
            page_size=page_size,
        )
    except RequestError as exc:
        _raise(exc)
    return {}


@router.post("")
def create_request(
    payload: RequestCreate,
    tenant: TenantContext = Depends(require_permission(PERM_SP_REQUEST_CREATE)),
) -> dict[str, Any]:
    try:
        doc = requests_service.create_request(
            payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except RequestError as exc:
        _raise(exc)
        return {}
    audit_service.record_event(
        tenant_id=tenant.tenant_id,
        action="portal.request.create"
        if not payload.submit
        else "portal.request.submit",
        resource_type="sp_request",
        resource_id=doc.get("request_id"),
        actor=_actor(tenant),
        details={
            "item_id": doc.get("item_id"),
            "status": doc.get("status"),
            "change_id": doc.get("change_id"),
        },
    )
    return doc


@router.get("/{request_id}")
def get_request(
    request_id: str,
    refresh_change: bool = Query(default=False),
    tenant: TenantContext = Depends(require_permission(PERM_SP_REQUEST_READ)),
) -> dict[str, Any]:
    try:
        if refresh_change:
            return requests_service.refresh_change_snapshot(
                request_id, tenant_id=tenant.tenant_id, actor=_actor(tenant)
            )
        return requests_service.get_request(
            tenant_id=tenant.tenant_id, request_id=request_id
        )
    except RequestError as exc:
        _raise(exc)
    return {}


@router.patch("/{request_id}")
def update_request(
    request_id: str,
    payload: RequestUpdate,
    tenant: TenantContext = Depends(require_permission(PERM_SP_REQUEST_CREATE)),
) -> dict[str, Any]:
    try:
        doc = requests_service.update_request(
            request_id, payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except RequestError as exc:
        _raise(exc)
        return {}
    audit_service.record_event(
        tenant_id=tenant.tenant_id,
        action="portal.request.update",
        resource_type="sp_request",
        resource_id=request_id,
        actor=_actor(tenant),
        details={"status": doc.get("status")},
    )
    return doc


@router.post("/{request_id}/submit")
def submit_request(
    request_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_SP_REQUEST_CREATE)),
) -> dict[str, Any]:
    try:
        doc = requests_service.submit_request(
            request_id, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except RequestError as exc:
        _raise(exc)
        return {}
    audit_service.record_event(
        tenant_id=tenant.tenant_id,
        action="portal.request.submit",
        resource_type="sp_request",
        resource_id=request_id,
        actor=_actor(tenant),
        details={
            "change_id": doc.get("change_id"),
            "change_type_key": doc.get("change_type_key"),
            "status": doc.get("status"),
        },
    )
    return doc


@router.post("/{request_id}/cancel")
def cancel_request(
    request_id: str,
    payload: CancelBody | None = None,
    tenant: TenantContext = Depends(require_permission(PERM_SP_REQUEST_CANCEL)),
) -> dict[str, Any]:
    body = payload or CancelBody()
    try:
        doc = requests_service.cancel_request(
            request_id,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
            comment=body.comment,
        )
    except RequestError as exc:
        _raise(exc)
        return {}
    audit_service.record_event(
        tenant_id=tenant.tenant_id,
        action="portal.request.cancel",
        resource_type="sp_request",
        resource_id=request_id,
        actor=_actor(tenant),
        details={
            "change_id": doc.get("change_id"),
            "status": doc.get("status"),
        },
    )
    return doc


@router.post("/{request_id}/link-incident")
def link_incident(
    request_id: str,
    payload: LinkIncidentBody,
    tenant: TenantContext = Depends(require_permission(PERM_SP_REQUEST_CREATE)),
) -> dict[str, Any]:
    """Optional incident link (SP8). Does not approve the request."""
    try:
        doc = requests_service.link_incident(
            request_id,
            tenant_id=tenant.tenant_id,
            linked_incident_id=payload.linked_incident_id,
            actor=_actor(tenant),
        )
    except RequestError as exc:
        _raise(exc)
        return {}
    return doc
