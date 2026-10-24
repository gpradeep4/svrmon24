"""CMDB relationship API — manual entry only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import verify_basic_credentials
from ..models.relationships import RelationshipCreate, RelationshipUpdate
from ..services import relationships as relationships_service
from ..services.relationships import RelationshipError

router = APIRouter(
    prefix="/api/relationships",
    tags=["cmdb-relationships"],
    dependencies=[Depends(verify_basic_credentials)],
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
) -> dict[str, Any]:
    try:
        return relationships_service.list_relationships(
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
def create_relationship(payload: RelationshipCreate) -> dict[str, Any]:
    try:
        return relationships_service.create_relationship(payload)
    except RelationshipError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{relationship_id}")
def get_relationship(relationship_id: str) -> dict[str, Any]:
    doc = relationships_service.get_relationship(relationship_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Relationship '{relationship_id}' not found"
        )
    return doc


@router.put("/{relationship_id}")
def update_relationship(
    relationship_id: str, payload: RelationshipUpdate
) -> dict[str, Any]:
    try:
        return relationships_service.update_relationship(relationship_id, payload)
    except RelationshipError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.delete("/{relationship_id}")
def delete_relationship(relationship_id: str) -> dict[str, Any]:
    try:
        return relationships_service.delete_relationship(relationship_id)
    except RelationshipError as exc:
        _raise(exc)
        raise  # pragma: no cover
