"""Service Portal catalog APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ...permissions import (
    PERM_SP_CATALOG_ADMIN,
    PERM_SP_CATALOG_READ,
    require_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..models.catalog import CatalogItemCreate, CatalogItemUpdate
from ..services import catalog as catalog_service
from ..services.catalog import CatalogError
from ..services.form_validate import FormValidationError, validate_form_values

router = APIRouter(prefix="/catalog", tags=["portal-catalog"])


def _raise(exc: CatalogError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


class FormValidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    form_values: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_catalog(
    domain: str | None = Query(default=None),
    enabled: bool | None = Query(default=True),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_SP_CATALOG_READ)),
) -> dict[str, Any]:
    try:
        return catalog_service.list_catalog(
            tenant_id=tenant.tenant_id,
            domain=domain,
            enabled=enabled,
            q=q,
            page=page,
            page_size=page_size,
        )
    except CatalogError as exc:
        _raise(exc)
    return {}


@router.get("/{item_id}")
def get_catalog_item(
    item_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_SP_CATALOG_READ)),
) -> dict[str, Any]:
    try:
        return catalog_service.get_catalog_item(
            tenant_id=tenant.tenant_id, item_id=item_id
        )
    except CatalogError as exc:
        _raise(exc)
    return {}


@router.post("")
def create_catalog_item(
    payload: CatalogItemCreate,
    tenant: TenantContext = Depends(require_permission(PERM_SP_CATALOG_ADMIN)),
) -> dict[str, Any]:
    try:
        item = catalog_service.create_catalog_item(
            payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except CatalogError as exc:
        _raise(exc)
        return {}
    audit_service.record_event(
        tenant_id=tenant.tenant_id,
        action="portal.catalog.create",
        resource_type="sp_catalog_item",
        resource_id=item.get("item_id"),
        actor=_actor(tenant),
        details={"key": item.get("key")},
    )
    return item


@router.patch("/{item_id}")
def update_catalog_item(
    item_id: str,
    payload: CatalogItemUpdate,
    tenant: TenantContext = Depends(require_permission(PERM_SP_CATALOG_ADMIN)),
) -> dict[str, Any]:
    try:
        item = catalog_service.update_catalog_item(
            item_id, payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except CatalogError as exc:
        _raise(exc)
        return {}
    audit_service.record_event(
        tenant_id=tenant.tenant_id,
        action="portal.catalog.update",
        resource_type="sp_catalog_item",
        resource_id=item_id,
        actor=_actor(tenant),
        details={},
    )
    return item


@router.post("/seed")
def seed_catalog(
    tenant: TenantContext = Depends(require_permission(PERM_SP_CATALOG_ADMIN)),
) -> dict[str, Any]:
    result = catalog_service.seed_catalog(
        tenant_id=tenant.tenant_id, actor=_actor(tenant)
    )
    audit_service.record_event(
        tenant_id=tenant.tenant_id,
        action="portal.catalog.seed",
        resource_type="sp_catalog_item",
        resource_id="seed",
        actor=_actor(tenant),
        details=result,
    )
    return result


@router.post("/{item_id}/validate")
def validate_catalog_form(
    item_id: str,
    payload: FormValidateBody,
    tenant: TenantContext = Depends(require_permission(PERM_SP_CATALOG_READ)),
) -> dict[str, Any]:
    try:
        item = catalog_service.get_catalog_item(
            tenant_id=tenant.tenant_id, item_id=item_id
        )
        values = validate_form_values(item.get("form_schema") or {}, payload.form_values)
    except CatalogError as exc:
        _raise(exc)
        return {}
    except FormValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"message": "form validation failed", "field_errors": exc.field_errors},
        ) from exc
    return {"ok": True, "form_values": values, "item_id": item_id}
