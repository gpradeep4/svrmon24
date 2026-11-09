"""Column-configuration APIs (Master Phase 8).

Routes: ``/api/column-configurations``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user
from ..models.column_configs import ColumnConfigurationUpdate
from ..permissions import PERM_CONFIG_WRITE, require_permission
from ..services import audit as audit_service
from ..services import column_configs as column_configs_service
from ..services.column_configs import ColumnConfigError
from ..tenant_context import TenantContext, require_tenant

router = APIRouter(
    prefix="/api/column-configurations",
    tags=["cmdb-column-configurations"],
    dependencies=[Depends(require_user)],
)


def _raise(exc: ColumnConfigError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("")
def list_column_configurations(
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    return {
        "items": column_configs_service.list_configurations(
            tenant_id=tenant.tenant_id
        ),
        "tenant_id": tenant.tenant_id,
        "collection": column_configs_service.COLLECTION,
    }


@router.get("/{grid_key}")
def get_column_configuration(
    grid_key: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return column_configs_service.get_configuration(
            grid_key, tenant_id=tenant.tenant_id
        )
    except ColumnConfigError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.put("/{grid_key}")
def put_column_configuration(
    grid_key: str,
    payload: ColumnConfigurationUpdate,
    tenant: TenantContext = Depends(require_permission(PERM_CONFIG_WRITE)),
) -> dict[str, Any]:
    try:
        doc = column_configs_service.upsert_configuration(
            grid_key, payload, tenant_id=tenant.tenant_id
        )
    except ColumnConfigError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="column_configuration.upsert",
        resource_type="column_configuration",
        resource_id=grid_key,
        request_method="PUT",
        request_path=f"/api/column-configurations/{grid_key}",
    )
    return doc


@router.delete("/{grid_key}")
def delete_column_configuration(
    grid_key: str,
    tenant: TenantContext = Depends(require_permission(PERM_CONFIG_WRITE)),
) -> dict[str, Any]:
    try:
        result = column_configs_service.reset_configuration(
            grid_key, tenant_id=tenant.tenant_id
        )
    except ColumnConfigError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="column_configuration.reset",
        resource_type="column_configuration",
        resource_id=grid_key,
        request_method="DELETE",
        request_path=f"/api/column-configurations/{grid_key}",
    )
    return result
