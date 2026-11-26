"""CMDB Contracts API (tenant-scoped, C4)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...auth import require_user
from ...permissions import PERM_CMDB_WRITE, require_permission
from ...services import audit as audit_service
from ...tenant_context import TenantContext, require_tenant
from ..models.contracts import ContractCreate, ContractUpdate
from ..services import contracts as contracts_service
from ..services.contracts import ContractError

router = APIRouter(
    prefix="/api/contracts",
    tags=["cmdb-contracts"],
    dependencies=[Depends(require_user)],
)


def _raise(exc: ContractError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("")
def list_contracts(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    return contracts_service.list_contracts(
        tenant_id=tenant.tenant_id, q=q, status=status, limit=limit
    )


@router.post("", status_code=201)
def create_contract(
    payload: ContractCreate,
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    try:
        doc = contracts_service.create_contract(
            payload, tenant_id=tenant.tenant_id
        )
    except ContractError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="contract.create",
        resource_type="cmdb_contracts",
        resource_id=doc.get("contract_id"),
        details={"status": doc.get("status")},
        request_method="POST",
        request_path="/api/contracts",
    )
    return doc


@router.get("/{contract_id}")
def get_contract(
    contract_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return contracts_service.get_contract(
            contract_id, tenant_id=tenant.tenant_id
        )
    except ContractError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.patch("/{contract_id}")
def update_contract(
    contract_id: str,
    payload: ContractUpdate,
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    try:
        doc = contracts_service.update_contract(
            contract_id, payload, tenant_id=tenant.tenant_id
        )
    except ContractError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="contract.update",
        resource_type="cmdb_contracts",
        resource_id=contract_id,
        details={},
        request_method="PATCH",
        request_path=f"/api/contracts/{contract_id}",
    )
    return doc


@router.delete("/{contract_id}")
def delete_contract(
    contract_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    try:
        result = contracts_service.delete_contract(
            contract_id, tenant_id=tenant.tenant_id
        )
    except ContractError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="contract.delete",
        resource_type="cmdb_contracts",
        resource_id=contract_id,
        details={},
        request_method="DELETE",
        request_path=f"/api/contracts/{contract_id}",
    )
    return result
