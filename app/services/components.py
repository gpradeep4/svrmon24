"""CMDB component inventory persistence and queries."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from ..db import require_database
from ..models.components import (
    TYPE_SPECIFIC_KEYS,
    ComponentCreate,
    ComponentType,
    ComponentUpdate,
    ComponentView,
    apply_component_update,
    build_component_document,
    to_inventory_row,
)
from ..serialization import serialize_document
from . import custom_fields as custom_fields_service
from .relationships import relationship_delete_warning

COLLECTION = "components"

_PREFIX: dict[ComponentType, str] = {
    ComponentType.SERVER: "srv",
    ComponentType.NETWORK: "net",
    ComponentType.MIDDLEWARE: "mware",
    ComponentType.DATABASE: "db",
    ComponentType.APPLICATION: "app",
}


class ComponentError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _collection() -> Collection:
    coll = require_database()[COLLECTION]
    coll.create_index([("component_id", ASCENDING)], unique=True)
    coll.create_index([("component_type", ASCENDING)])
    coll.create_index([("environment", ASCENDING)])
    coll.create_index([("status", ASCENDING)])
    coll.create_index([("name", ASCENDING)])
    coll.create_index([("hostname", ASCENDING)])
    return coll


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_component_id(component_type: ComponentType) -> str:
    prefix = _PREFIX[component_type]
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def ensure_type_keys(doc: dict[str, Any]) -> dict[str, Any]:
    """Backfill missing type-specific keys as None for older documents."""
    for keys in TYPE_SPECIFIC_KEYS.values():
        for key in keys:
            doc.setdefault(key, None)
    doc.setdefault("custom_fields", {})
    return doc


def get_component(component_id: str) -> dict[str, Any] | None:
    doc = _collection().find_one({"component_id": component_id})
    if doc is None:
        return None
    return serialize_document(ensure_type_keys(doc))  # type: ignore[return-value]


def create_component(payload: ComponentCreate) -> dict[str, Any]:
    custom_fields_service.validate_component_custom_fields(
        payload.component_type, payload.custom_fields or {}
    )
    component_id = payload.component_id or generate_component_id(payload.component_type)
    now = _now()
    doc = build_component_document(payload, component_id=component_id, now=now)
    try:
        _collection().insert_one(doc)
    except DuplicateKeyError as exc:
        raise ComponentError(
            f"Component ID '{component_id}' already exists",
            status_code=409,
        ) from exc
    return serialize_document(ensure_type_keys(doc))  # type: ignore[return-value]


def update_component(component_id: str, payload: ComponentUpdate) -> dict[str, Any]:
    coll = _collection()
    existing = coll.find_one({"component_id": component_id})
    if existing is None:
        raise ComponentError(f"Component '{component_id}' not found", status_code=404)

    existing = ensure_type_keys(existing)
    try:
        updated = apply_component_update(existing, payload, now=_now())
    except ValueError as exc:
        raise ComponentError(str(exc), status_code=422) from exc

    ctype = ComponentType(updated["component_type"])
    custom_fields_service.validate_component_custom_fields(
        ctype, updated.get("custom_fields") or {}
    )

    # Persist without Mongo _id mutation issues
    to_set = {k: v for k, v in updated.items() if k != "_id"}
    coll.update_one({"component_id": component_id}, {"$set": to_set})
    return get_component(component_id)  # type: ignore[return-value]


def delete_preview(component_id: str) -> dict[str, Any]:
    doc = get_component(component_id)
    if doc is None:
        raise ComponentError(f"Component '{component_id}' not found", status_code=404)
    warning = relationship_delete_warning(component_id)
    return {
        "component": doc,
        "can_delete": True,
        "requires_confirmation": True,
        "relationship_warning": warning,
    }


def delete_component(component_id: str, *, confirmed: bool = False) -> dict[str, Any]:
    if not confirmed:
        raise ComponentError(
            "Deletion requires confirmation (set confirmed=true)",
            status_code=400,
        )
    preview = delete_preview(component_id)
    result = _collection().delete_one({"component_id": component_id})
    if result.deleted_count == 0:
        raise ComponentError(f"Component '{component_id}' not found", status_code=404)
    return {
        "deleted": True,
        "component_id": component_id,
        "relationship_warning": preview["relationship_warning"],
    }


def _build_query(
    *,
    q: str | None,
    component_type: str | None,
    environment: str | None,
    status: str | None,
    os_family: str | None,
    product_type: str | None,
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if component_type:
        query["component_type"] = component_type
    if environment:
        query["environment"] = environment
    if status:
        query["status"] = status
    if os_family:
        query["os_family"] = os_family
    if product_type:
        query["product_type"] = product_type

    if q:
        pattern = re.compile(re.escape(q.strip()), re.IGNORECASE)
        query["$or"] = [
            {"component_id": pattern},
            {"name": pattern},
            {"hostname": pattern},
            {"device_name": pattern},
            {"application_name": pattern},
            {"environment": pattern},
            {"product_type": pattern},
            {"os_family": pattern},
        ]
    return query


def list_components(
    *,
    q: str | None = None,
    component_type: str | None = None,
    environment: str | None = None,
    status: str | None = None,
    os_family: str | None = None,
    product_type: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    allowed_sort = {
        "component_id",
        "name",
        "hostname",
        "component_type",
        "environment",
        "status",
        "os_family",
        "os_version",
        "product_type",
        "product_version",
        "created_at",
        "updated_at",
    }
    if sort_by not in allowed_sort:
        sort_by = "updated_at"
    direction = DESCENDING if sort_dir.lower() == "desc" else ASCENDING

    query = _build_query(
        q=q,
        component_type=component_type,
        environment=environment,
        status=status,
        os_family=os_family,
        product_type=product_type,
    )
    coll = _collection()
    total = coll.count_documents(query)
    cursor = (
        coll.find(query)
        .sort(sort_by, direction)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    for raw in cursor:
        doc = serialize_document(ensure_type_keys(raw))
        assert doc is not None
        items.append(doc)
        inventory.append(to_inventory_row(doc).model_dump())

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "items": items,
        "inventory": inventory,
    }


def as_view(doc: dict[str, Any]) -> ComponentView:
    return ComponentView.model_validate(doc)
