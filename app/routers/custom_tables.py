"""Custom entity table APIs.

Routes:
  - ``/api/custom-tables`` — table definitions + columns
  - ``/api/custom-tables/{table_key}/records`` — row CRUD
  - ``/api/entity-refs`` — unified CMDB + custom picker for relationships
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_user
from ..models.custom_tables import (
    CustomColumnCreate,
    CustomColumnUpdate,
    CustomRecordCreate,
    CustomRecordUpdate,
    CustomTableCreate,
    CustomTableUpdate,
)
from ..services import custom_tables as custom_tables_service
from ..services.custom_tables import CustomTableError
from ..tenant_context import TenantContext, require_tenant

router = APIRouter(
    prefix="/api/custom-tables",
    tags=["cmdb-custom-tables"],
    dependencies=[Depends(require_user)],
)

entity_refs_router = APIRouter(
    prefix="/api/entity-refs",
    tags=["cmdb-entity-refs"],
    dependencies=[Depends(require_user)],
)


def _raise(exc: CustomTableError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("")
def list_custom_tables(
    active_only: bool = Query(default=False),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    return {
        "items": custom_tables_service.list_tables(
            tenant_id=tenant.tenant_id, active_only=active_only
        ),
        "tenant_id": tenant.tenant_id,
        "definitions_collection": custom_tables_service.DEFINITIONS_COLLECTION,
        "records_collection": custom_tables_service.RECORDS_COLLECTION,
        "storage_mode": "single_collection_with_table_key",
    }


@router.post("", status_code=201)
def create_custom_table(
    payload: CustomTableCreate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return custom_tables_service.create_table(
            payload, tenant_id=tenant.tenant_id
        )
    except CustomTableError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{table_key}")
def get_custom_table(
    table_key: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    doc = custom_tables_service.get_table(table_key, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Custom table '{table_key}' not found"
        )
    return doc


@router.put("/{table_key}")
def update_custom_table(
    table_key: str,
    payload: CustomTableUpdate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return custom_tables_service.update_table(
            table_key, payload, tenant_id=tenant.tenant_id
        )
    except CustomTableError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.delete("/{table_key}")
def delete_custom_table(
    table_key: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return custom_tables_service.delete_table(
            table_key, tenant_id=tenant.tenant_id
        )
    except CustomTableError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/{table_key}/columns", status_code=201)
def add_custom_column(
    table_key: str,
    payload: CustomColumnCreate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return custom_tables_service.add_column(
            table_key, payload, tenant_id=tenant.tenant_id
        )
    except CustomTableError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.put("/{table_key}/columns/{column_key}")
def update_custom_column(
    table_key: str,
    column_key: str,
    payload: CustomColumnUpdate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return custom_tables_service.update_column(
            table_key, column_key, payload, tenant_id=tenant.tenant_id
        )
    except CustomTableError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.delete("/{table_key}/columns/{column_key}")
def delete_custom_column(
    table_key: str,
    column_key: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return custom_tables_service.delete_column(
            table_key, column_key, tenant_id=tenant.tenant_id
        )
    except CustomTableError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{table_key}/records")
def list_custom_records(
    table_key: str,
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return custom_tables_service.list_records(
            table_key,
            tenant_id=tenant.tenant_id,
            q=q,
            page=page,
            page_size=page_size,
        )
    except CustomTableError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/{table_key}/records", status_code=201)
def create_custom_record(
    table_key: str,
    payload: CustomRecordCreate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return custom_tables_service.create_record(
            table_key, payload, tenant_id=tenant.tenant_id
        )
    except CustomTableError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{table_key}/records/{record_id}")
def get_custom_record(
    table_key: str,
    record_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    doc = custom_tables_service.get_record(
        table_key, record_id, tenant_id=tenant.tenant_id
    )
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Record '{record_id}' not found on table '{table_key}'",
        )
    return doc


@router.put("/{table_key}/records/{record_id}")
def update_custom_record(
    table_key: str,
    record_id: str,
    payload: CustomRecordUpdate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return custom_tables_service.update_record(
            table_key, record_id, payload, tenant_id=tenant.tenant_id
        )
    except CustomTableError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.delete("/{table_key}/records/{record_id}")
def delete_custom_record(
    table_key: str,
    record_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return custom_tables_service.delete_record(
            table_key, record_id, tenant_id=tenant.tenant_id
        )
    except CustomTableError as exc:
        _raise(exc)
        raise  # pragma: no cover


@entity_refs_router.get("")
def list_entity_refs(
    q: str | None = Query(default=None),
    table: str | None = Query(
        default=None,
        description="Filter by CMDB component type or custom table_key",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return custom_tables_service.list_entity_refs(
            tenant_id=tenant.tenant_id, q=q, table=table, limit=limit
        )
    except CustomTableError as exc:
        _raise(exc)
        raise  # pragma: no cover
