"""CMDB relationship API — manual entry only (tenant-scoped)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_user
from ..models.relationships import RelationshipCreate, RelationshipUpdate
from ..services import audit as audit_service
from ..services import relationships as relationships_service
from ..services.relationships import RelationshipError
from ..tenant_context import TenantContext, require_tenant

router = APIRouter(
    prefix="/api/relationships",
    tags=["cmdb-relationships"],
    dependencies=[Depends(require_user)],
)


def _raise(exc: RelationshipError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/types")
def list_relationship_types() -> dict[str, Any]:
    """Documented relationship types with meaning and direction."""
    return relationships_service.relationship_type_catalog()


@router.get("")
def list_relationships(
    q: str | None = Query(default=None),
    source_component_id: str | None = Query(default=None),
    target_component_id: str | None = Query(default=None),
    component_id: str | None = Query(
        default=None, description="Match as source or target"
    ),
    relationship_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return relationships_service.list_relationships(
            tenant_id=tenant.tenant_id,
            q=q,
            source_component_id=source_component_id,
            target_component_id=target_component_id,
            component_id=component_id,
            relationship_type=relationship_type,
            page=page,
            page_size=page_size,
        )
    except RelationshipError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("", status_code=201)
def create_relationship(
    payload: RelationshipCreate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        doc = relationships_service.create_relationship(
            payload, tenant_id=tenant.tenant_id
        )
    except RelationshipError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="relationship.create",
        resource_type="relationship",
        resource_id=doc.get("relationship_id"),
        details={
            "relationship_type": doc.get("relationship_type"),
            "source_component_id": doc.get("source_component_id"),
            "target_component_id": doc.get("target_component_id"),
        },
        request_method="POST",
        request_path="/api/relationships",
    )
    return doc


@router.get("/{relationship_id}")
def get_relationship(
    relationship_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    doc = relationships_service.get_relationship(
        relationship_id, tenant_id=tenant.tenant_id
    )
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Relationship '{relationship_id}' not found"
        )
    return doc


@router.put("/{relationship_id}")
def update_relationship(
    relationship_id: str,
    payload: RelationshipUpdate,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        doc = relationships_service.update_relationship(
            relationship_id, payload, tenant_id=tenant.tenant_id
        )
    except RelationshipError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="relationship.update",
        resource_type="relationship",
        resource_id=relationship_id,
        request_method="PUT",
        request_path=f"/api/relationships/{relationship_id}",
    )
    return doc


@router.delete("/{relationship_id}")
def delete_relationship(
    relationship_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        result = relationships_service.delete_relationship(
            relationship_id, tenant_id=tenant.tenant_id
        )
    except RelationshipError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="relationship.delete",
        resource_type="relationship",
        resource_id=relationship_id,
        request_method="DELETE",
        request_path=f"/api/relationships/{relationship_id}",
    )
    return result
