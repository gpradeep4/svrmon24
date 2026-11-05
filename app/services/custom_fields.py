"""CMDB field-definition persistence (tenant-scoped, Master Phase 7).

Canonical collection: ``cmdb_field_definitions``.
Legacy ``custom_field_definitions`` is a migration source only.
``/api/custom-fields`` remains a facade over this service.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from ..db import require_database
from ..models.custom_fields import (
    BUILTIN_FIELD_KEYS,
    CustomFieldCreate,
    CustomFieldDefinition,
    CustomFieldUpdate,
    FieldOrigin,
    FieldStorage,
    builtin_field_specs,
    field_applies_to_type,
)
from ..models.components import ComponentType
from ..serialization import serialize_document
from ..tenancy import require_tenant_id, stamp_tenant_id, tenant_filter

COLLECTION = "cmdb_field_definitions"
LEGACY_COLLECTION = "custom_field_definitions"


class CustomFieldError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# Phase 7 aliases
FieldDefinitionError = CustomFieldError


def _collection() -> Collection:
    coll = require_database()[COLLECTION]
    # Uniqueness is per-tenant (multi-org safe).
    coll.create_index(
        [("tenant_id", ASCENDING), ("field_key", ASCENDING)],
        unique=True,
        name="tenant_field_key_unique",
    )
    coll.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")
    coll.create_index(
        [("tenant_id", ASCENDING), ("origin", ASCENDING)],
        name="tenant_origin_idx",
    )
    return coll


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Ensure Phase 7 fields exist on serialized docs (legacy migrate gaps)."""
    if doc is None:
        return None
    doc.setdefault("origin", FieldOrigin.CUSTOM.value)
    doc.setdefault("storage", FieldStorage.CUSTOM_FIELDS.value)
    doc.setdefault("description", None)
    doc.setdefault("active", True)
    doc.setdefault("locked", doc.get("origin") == FieldOrigin.BUILTIN.value)
    return doc


def list_definitions(
    *,
    tenant_id: str,
    component_type: str | None = None,
    origin: str | None = None,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    tid = require_tenant_id(tenant_id)
    query: dict[str, Any] = {**tenant_filter(tid)}
    if origin:
        query["origin"] = origin
    docs = list(_collection().find(query).sort("field_key", ASCENDING))
    serialized = [_normalize_doc(serialize_document(doc)) for doc in docs]
    serialized = [d for d in serialized if d is not None]
    if not include_inactive:
        serialized = [d for d in serialized if d.get("active", True)]
    if component_type:
        ctype = ComponentType(component_type) if component_type != "*" else None
        if ctype is not None:
            serialized = [d for d in serialized if field_applies_to_type(d, ctype)]
    return serialized  # type: ignore[return-value]


def get_definition(field_key: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _collection().find_one({"field_key": field_key, **tenant_filter(tid)})
    return _normalize_doc(serialize_document(doc))  # type: ignore[return-value]


def ensure_builtin_definitions(*, tenant_id: str) -> dict[str, Any]:
    """Idempotently seed locked OS/product built-in field definitions for a tenant."""
    tid = require_tenant_id(tenant_id)
    coll = _collection()
    now = _now()
    created = 0
    skipped = 0
    for spec in builtin_field_specs():
        existing = coll.find_one({"field_key": spec["field_key"], **tenant_filter(tid)})
        if existing is not None:
            # Re-assert locked/native shape so OS/product pairs never collapse.
            coll.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "label": spec["label"],
                        "field_type": spec["field_type"],
                        "applies_to": list(spec["applies_to"]),
                        "origin": FieldOrigin.BUILTIN.value,
                        "storage": FieldStorage.NATIVE.value,
                        "locked": True,
                        "active": True,
                        "description": spec.get("description"),
                        "updated_at": now,
                    }
                },
            )
            skipped += 1
            continue
        doc = {
            **spec,
            "created_at": now,
            "updated_at": now,
        }
        stamp_tenant_id(doc, tenant_id=tid)
        try:
            coll.insert_one(doc)
            created += 1
        except DuplicateKeyError:
            skipped += 1
    return {
        "tenant_id": tid,
        "created": created,
        "ensured": skipped + created,
        "builtin_keys": sorted(BUILTIN_FIELD_KEYS),
    }


def create_definition(payload: CustomFieldCreate, *, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    ensure_builtin_definitions(tenant_id=tid)
    if payload.field_key in BUILTIN_FIELD_KEYS:
        raise CustomFieldError(
            f"field_key '{payload.field_key}' is reserved for a built-in native field",
            status_code=409,
        )
    now = _now()
    doc = {
        "field_key": payload.field_key,
        "label": payload.label,
        "field_type": payload.field_type.value,
        "applies_to": list(payload.applies_to),
        "required": payload.required,
        "enum_values": list(payload.enum_values),
        "origin": FieldOrigin.CUSTOM.value,
        "storage": FieldStorage.CUSTOM_FIELDS.value,
        "description": payload.description,
        "active": payload.active,
        "locked": False,
        "created_at": now,
        "updated_at": now,
    }
    stamp_tenant_id(doc, tenant_id=tid)
    try:
        _collection().insert_one(doc)
    except DuplicateKeyError as exc:
        raise CustomFieldError(
            f"Custom field '{payload.field_key}' already exists",
            status_code=409,
        ) from exc
    return _normalize_doc(serialize_document(doc))  # type: ignore[return-value]


def update_definition(
    field_key: str, payload: CustomFieldUpdate, *, tenant_id: str
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    coll = _collection()
    existing = coll.find_one({"field_key": field_key, **tenant_filter(tid)})
    if existing is None:
        raise CustomFieldError(f"Custom field '{field_key}' not found", status_code=404)

    origin = existing.get("origin", FieldOrigin.CUSTOM.value)
    locked = bool(existing.get("locked")) or origin == FieldOrigin.BUILTIN.value

    data = payload.model_dump(exclude_unset=True)
    if "field_type" in data and data["field_type"] is not None:
        data["field_type"] = data["field_type"].value

    if locked:
        # Built-ins: allow label/description/active tweaks only — never collapse
        # OS Family/Version or Product Type/Version via applies_to/type/storage.
        forbidden = {"field_type", "applies_to", "required", "enum_values"}
        attempted = forbidden.intersection(data)
        if attempted:
            raise CustomFieldError(
                f"Built-in field '{field_key}' cannot change {sorted(attempted)} "
                "(OS/product pairs must remain separate native fields)",
                status_code=400,
            )
        # Force native/builtin invariants on every update.
        data["origin"] = FieldOrigin.BUILTIN.value
        data["storage"] = FieldStorage.NATIVE.value
        data["locked"] = True
        data["applies_to"] = list(existing.get("applies_to") or [])

    if not data:
        return _normalize_doc(serialize_document(existing))  # type: ignore[return-value]

    if not locked:
        merged = {**existing, **data}
        CustomFieldCreate.model_validate(
            {
                "field_key": field_key,
                "label": merged["label"],
                "field_type": merged["field_type"],
                "applies_to": merged.get("applies_to") or ["*"],
                "required": merged.get("required", False),
                "enum_values": merged.get("enum_values") or [],
                "description": merged.get("description"),
                "active": merged.get("active", True),
            }
        )

    data["updated_at"] = _now()
    stamp_tenant_id(data, tenant_id=tid)
    # Never allow writes to change storage/origin away from custom for custom fields
    # or away from builtin/native for builtins (already forced above for locked).
    if not locked:
        data["origin"] = FieldOrigin.CUSTOM.value
        data["storage"] = FieldStorage.CUSTOM_FIELDS.value
        data["locked"] = False

    coll.update_one({"field_key": field_key, **tenant_filter(tid)}, {"$set": data})
    return get_definition(field_key, tenant_id=tid)  # type: ignore[return-value]


def delete_definition(field_key: str, *, tenant_id: str) -> None:
    tid = require_tenant_id(tenant_id)
    existing = _collection().find_one({"field_key": field_key, **tenant_filter(tid)})
    if existing is None:
        raise CustomFieldError(f"Custom field '{field_key}' not found", status_code=404)
    if (
        existing.get("locked")
        or existing.get("origin") == FieldOrigin.BUILTIN.value
        or field_key in BUILTIN_FIELD_KEYS
    ):
        raise CustomFieldError(
            f"Built-in field '{field_key}' cannot be deleted",
            status_code=400,
        )
    result = _collection().delete_one({"field_key": field_key, **tenant_filter(tid)})
    if result.deleted_count == 0:
        raise CustomFieldError(f"Custom field '{field_key}' not found", status_code=404)


def validate_component_custom_fields(
    component_type: ComponentType,
    custom_fields: dict[str, Any],
    *,
    tenant_id: str,
) -> None:
    """Validate ``custom_fields`` against **custom** (storage=custom_fields) defs."""
    definitions = list_definitions(tenant_id=tenant_id, origin=FieldOrigin.CUSTOM.value)
    applicable = [
        d
        for d in definitions
        if d.get("storage", FieldStorage.CUSTOM_FIELDS.value)
        == FieldStorage.CUSTOM_FIELDS.value
        and field_applies_to_type(d, component_type)
    ]
    known_keys = {d["field_key"] for d in applicable}

    # Built-in native keys must never be stuffed into custom_fields.
    native_collision = set(custom_fields).intersection(BUILTIN_FIELD_KEYS)
    if native_collision:
        raise CustomFieldError(
            f"Built-in native fields {sorted(native_collision)} must not be set via "
            "custom_fields (use component attributes)",
            status_code=422,
        )

    _ = known_keys  # unknown custom keys are allowed (forward-compatible)

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
    return CustomFieldDefinition.model_validate(_normalize_doc(doc))
