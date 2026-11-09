"""CMDB component inventory API (tenant-scoped)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_user
from ..models.components import COMPONENT_TYPES, ComponentCreate, ComponentUpdate
from ..services import audit as audit_service
from ..services import components as components_service
from ..services.components import ComponentError
from ..tenant_context import TenantContext, require_tenant

router = APIRouter(
    prefix="/api/components",
    tags=["cmdb-components"],
    dependencies=[Depends(require_user)],
)


def _raise(exc: ComponentError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/types")
def list_component_types() -> dict[str, Any]:
    return {"types": list(COMPONENT_TYPES)}


@router.get("")
def list_components(
    q: str | None = Query(default=None, description="Search text"),
    component_type: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    status: str | None = Query(default=None),
    os_family: str | None = Query(default=None),
    product_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc", pattern="^(?i)(asc|desc)$"),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    if component_type and component_type not in COMPONENT_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid component_type: {component_type}")
    return components_service.list_components(
        tenant_id=tenant.tenant_id,
        q=q,
        component_type=component_type,
        environment=environment,
        status=status,
        os_family=os_family,
        product_type=product_type,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.post("", status_code=201)
def create_component(
    payload: ComponentCreate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        doc = components_service.create_component(payload, tenant_id=tenant.tenant_id)
    except ComponentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    except Exception as exc:
        from ..services.custom_fields import CustomFieldError

        if isinstance(exc, CustomFieldError):
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        raise
    audit_service.record_from_tenant(
        tenant,
        action="component.create",
        resource_type="component",
        resource_id=doc.get("component_id"),
        details={
            "component_type": doc.get("component_type"),
            "name": doc.get("name"),
        },
        request_method="POST",
        request_path="/api/components",
    )
    return doc


@router.get("/{component_id}")
def get_component(
    component_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    doc = components_service.get_component(component_id, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Component '{component_id}' not found")
    return doc


@router.put("/{component_id}")
def update_component(
    component_id: str,
    payload: ComponentUpdate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        doc = components_service.update_component(
            component_id, payload, tenant_id=tenant.tenant_id
        )
    except ComponentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    except Exception as exc:
        from ..services.custom_fields import CustomFieldError

        if isinstance(exc, CustomFieldError):
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        raise
    audit_service.record_from_tenant(
        tenant,
        action="component.update",
        resource_type="component",
        resource_id=component_id,
        details={"component_type": doc.get("component_type")},
        request_method="PUT",
        request_path=f"/api/components/{component_id}",
    )
    return doc


@router.get("/{component_id}/delete-preview")
def delete_preview(
    component_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return components_service.delete_preview(
            component_id, tenant_id=tenant.tenant_id
        )
    except ComponentError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.delete("/{component_id}")
def delete_component(
    component_id: str,
    confirmed: bool = Query(default=False, description="Must be true to delete"),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        result = components_service.delete_component(
            component_id, confirmed=confirmed, tenant_id=tenant.tenant_id
        )
    except ComponentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    if confirmed:
        audit_service.record_from_tenant(
            tenant,
            action="component.delete",
            resource_type="component",
            resource_id=component_id,
            request_method="DELETE",
            request_path=f"/api/components/{component_id}",
        )
    return result
