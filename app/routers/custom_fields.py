"""Custom field definition API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_user
from ..models.custom_fields import CustomFieldCreate, CustomFieldUpdate
from ..services import custom_fields as custom_fields_service
from ..services.custom_fields import CustomFieldError

router = APIRouter(
    prefix="/api/custom-fields",
    tags=["cmdb-custom-fields"],
    dependencies=[Depends(require_user)],
)


def _raise(exc: CustomFieldError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("")
def list_custom_fields(
    component_type: str | None = Query(default=None),
) -> dict[str, Any]:
    return {"items": custom_fields_service.list_definitions(component_type=component_type)}


@router.post("", status_code=201)
def create_custom_field(payload: CustomFieldCreate) -> dict[str, Any]:
    try:
        return custom_fields_service.create_definition(payload)
    except CustomFieldError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{field_key}")
def get_custom_field(field_key: str) -> dict[str, Any]:
    doc = custom_fields_service.get_definition(field_key)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Custom field '{field_key}' not found")
    return doc


@router.put("/{field_key}")
def update_custom_field(field_key: str, payload: CustomFieldUpdate) -> dict[str, Any]:
    try:
        return custom_fields_service.update_definition(field_key, payload)
    except CustomFieldError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.delete("/{field_key}")
def delete_custom_field(field_key: str) -> dict[str, str]:
    try:
        custom_fields_service.delete_definition(field_key)
    except CustomFieldError as exc:
        _raise(exc)
        raise  # pragma: no cover
    return {"deleted": field_key}
