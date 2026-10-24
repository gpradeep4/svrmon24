"""Custom-field definition persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from ..db import require_database
from ..models.custom_fields import (
    CustomFieldCreate,
    CustomFieldDefinition,
    CustomFieldUpdate,
    field_applies_to_type,
)
from ..models.components import ComponentType
from ..serialization import serialize_document

COLLECTION = "custom_field_definitions"


class CustomFieldError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _collection() -> Collection:
    coll = require_database()[COLLECTION]
    coll.create_index([("field_key", ASCENDING)], unique=True)
    return coll


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_definitions(*, component_type: str | None = None) -> list[dict[str, Any]]:
    docs = list(_collection().find().sort("field_key", ASCENDING))
    serialized = [serialize_document(doc) for doc in docs]
    if component_type:
        ctype = ComponentType(component_type) if component_type != "*" else None
        if ctype is not None:
            serialized = [d for d in serialized if field_applies_to_type(d, ctype)]
    return serialized  # type: ignore[return-value]


def get_definition(field_key: str) -> dict[str, Any] | None:
    doc = _collection().find_one({"field_key": field_key})
    return serialize_document(doc)  # type: ignore[return-value]


def create_definition(payload: CustomFieldCreate) -> dict[str, Any]:
    now = _now()
    doc = {
        "field_key": payload.field_key,
        "label": payload.label,
        "field_type": payload.field_type.value,
        "applies_to": list(payload.applies_to),
        "required": payload.required,
        "enum_values": list(payload.enum_values),
        "created_at": now,
        "updated_at": now,
    }
    try:
        _collection().insert_one(doc)
    except DuplicateKeyError as exc:
        raise CustomFieldError(
            f"Custom field '{payload.field_key}' already exists",
            status_code=409,
        ) from exc
    return serialize_document(doc)  # type: ignore[return-value]


def update_definition(field_key: str, payload: CustomFieldUpdate) -> dict[str, Any]:
    coll = _collection()
    existing = coll.find_one({"field_key": field_key})
    if existing is None:
        raise CustomFieldError(f"Custom field '{field_key}' not found", status_code=404)

    data = payload.model_dump(exclude_unset=True)
    if "field_type" in data and data["field_type"] is not None:
        data["field_type"] = data["field_type"].value
    if not data:
        return serialize_document(existing)  # type: ignore[return-value]

    # Validate enum consistency after merge
    merged = {**existing, **data}
    CustomFieldCreate.model_validate(
        {
            "field_key": field_key,
            "label": merged["label"],
            "field_type": merged["field_type"],
            "applies_to": merged.get("applies_to") or ["*"],
            "required": merged.get("required", False),
            "enum_values": merged.get("enum_values") or [],
        }
    )
    data["updated_at"] = _now()
    coll.update_one({"field_key": field_key}, {"$set": data})
    return get_definition(field_key)  # type: ignore[return-value]


def delete_definition(field_key: str) -> None:
    result = _collection().delete_one({"field_key": field_key})
    if result.deleted_count == 0:
        raise CustomFieldError(f"Custom field '{field_key}' not found", status_code=404)


def validate_component_custom_fields(
    component_type: ComponentType,
    custom_fields: dict[str, Any],
) -> None:
    """Validate custom_fields against configured definitions (required + types)."""
    definitions = list_definitions()
    applicable = [d for d in definitions if field_applies_to_type(d, component_type)]
    known_keys = {d["field_key"] for d in applicable}

    unknown = set(custom_fields) - known_keys
    # Allow unknown keys for forward-compat / free-form, but warn via exception only if
    # definitions exist and required ones are missing. Unknown keys are permitted.
    _ = unknown

    for definition in applicable:
        key = definition["field_key"]
        required = definition.get("required", False)
        if required and (key not in custom_fields or custom_fields[key] in (None, "")):
            raise CustomFieldError(
                f"Required custom field '{key}' is missing",
                status_code=422,
            )
        if key not in custom_fields:
            continue
        value = custom_fields[key]
        ftype = definition.get("field_type")
        if ftype == "number" and value is not None and not isinstance(value, (int, float)):
            raise CustomFieldError(f"Custom field '{key}' must be a number", status_code=422)
        if ftype == "boolean" and value is not None and not isinstance(value, bool):
            raise CustomFieldError(f"Custom field '{key}' must be a boolean", status_code=422)
        if ftype == "enum":
            allowed = definition.get("enum_values") or []
            if value is not None and value not in allowed:
                raise CustomFieldError(
                    f"Custom field '{key}' must be one of {allowed}",
                    status_code=422,
                )


def as_definition_model(doc: dict[str, Any]) -> CustomFieldDefinition:
    return CustomFieldDefinition.model_validate(doc)
