"""Field-definition APIs (Master Phase 7).

Canonical routes: ``/api/field-definitions``.
Facade (unchanged path): ``/api/custom-fields`` — lists **custom** defs by default
so the vanilla Inventory form keeps attaching values to ``custom_fields``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_user
from ..models.custom_fields import CustomFieldCreate, CustomFieldUpdate, FieldOrigin
from ..services import custom_fields as custom_fields_service
from ..services.custom_fields import CustomFieldError
from ..tenant_context import TenantContext, require_tenant

# Canonical Phase 7 router
router = APIRouter(
    prefix="/api/field-definitions",
    tags=["cmdb-field-definitions"],
    dependencies=[Depends(require_user)],
)

# Backward-compatible facade
facade_router = APIRouter(
    prefix="/api/custom-fields",
    tags=["cmdb-custom-fields"],
    dependencies=[Depends(require_user)],
)


def _raise(exc: CustomFieldError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _list_impl(
    *,
    tenant: TenantContext,
    component_type: str | None,
    origin: str | None,
    include_inactive: bool,
) -> dict[str, Any]:
    # Ensure builtins exist for the current tenant on first list.
    custom_fields_service.ensure_builtin_definitions(tenant_id=tenant.tenant_id)
    return {
        "items": custom_fields_service.list_definitions(
            tenant_id=tenant.tenant_id,
            component_type=component_type,
            origin=origin,
            include_inactive=include_inactive,
        ),
        "tenant_id": tenant.tenant_id,
        "collection": custom_fields_service.COLLECTION,
    }


@router.get("")
def list_field_definitions(
    component_type: str | None = Query(default=None),
    origin: str | None = Query(
        default=None,
        description="Filter by origin: custom | builtin (omit for all).",
    ),
    include_inactive: bool = Query(default=False),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    if origin is not None and origin not in {o.value for o in FieldOrigin}:
        raise HTTPException(status_code=422, detail="origin must be 'custom' or 'builtin'")
    return _list_impl(
        tenant=tenant,
        component_type=component_type,
        origin=origin,
        include_inactive=include_inactive,
    )


@facade_router.get("")
def list_custom_fields(
    component_type: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Facade: custom-origin definitions only (Inventory custom-fields form)."""
    return _list_impl(
        tenant=tenant,
        component_type=component_type,
        origin=FieldOrigin.CUSTOM.value,
        include_inactive=include_inactive,
    )


def _create_impl(payload: CustomFieldCreate, tenant: TenantContext) -> dict[str, Any]:
    try:
        return custom_fields_service.create_definition(
            payload, tenant_id=tenant.tenant_id
        )
    except CustomFieldError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("", status_code=201)
def create_field_definition(
    payload: CustomFieldCreate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    return _create_impl(payload, tenant)


@facade_router.post("", status_code=201)
def create_custom_field(
    payload: CustomFieldCreate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    return _create_impl(payload, tenant)


def _get_impl(field_key: str, tenant: TenantContext) -> dict[str, Any]:
    doc = custom_fields_service.get_definition(field_key, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Custom field '{field_key}' not found")
    return doc


@router.get("/{field_key}")
def get_field_definition(
    field_key: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    return _get_impl(field_key, tenant)


@facade_router.get("/{field_key}")
def get_custom_field(
    field_key: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    return _get_impl(field_key, tenant)


def _update_impl(
    field_key: str, payload: CustomFieldUpdate, tenant: TenantContext
) -> dict[str, Any]:
    try:
        return custom_fields_service.update_definition(
            field_key, payload, tenant_id=tenant.tenant_id
        )
    except CustomFieldError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.put("/{field_key}")
def update_field_definition(
    field_key: str,
    payload: CustomFieldUpdate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    return _update_impl(field_key, payload, tenant)


@facade_router.put("/{field_key}")
def update_custom_field(
    field_key: str,
    payload: CustomFieldUpdate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    return _update_impl(field_key, payload, tenant)


def _delete_impl(field_key: str, tenant: TenantContext) -> dict[str, str]:
    try:
        custom_fields_service.delete_definition(
            field_key, tenant_id=tenant.tenant_id
        )
    except CustomFieldError as exc:
        _raise(exc)
        raise  # pragma: no cover
    return {"deleted": field_key}


@router.delete("/{field_key}")
def delete_field_definition(
    field_key: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, str]:
    return _delete_impl(field_key, tenant)


@facade_router.delete("/{field_key}")
def delete_custom_field(
    field_key: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, str]:
    return _delete_impl(field_key, tenant)
