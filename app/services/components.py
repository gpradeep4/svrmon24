"""CMDB component inventory — typed collections with stable API facade.

Master Phase 6: documents live in ``cmdb_servers`` / ``cmdb_network`` /
``cmdb_middleware`` / ``cmdb_databases`` / ``cmdb_applications``. The public
``/api/components*`` surface is unchanged; callers still pass ``tenant_id``.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
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
from ..tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id, tenant_filter
from . import custom_fields as custom_fields_service
from .cmdb_collections import (
    LEGACY_COMPONENTS_COLLECTION,
    TYPED_CMDB_COLLECTIONS,
    collection_name_for_type,
    component_id_taken,
    ensure_typed_cmdb_indexes,
    find_raw_across_typed,
    get_typed_collection,
    typed_collection_names,
)
from .relationships import relationship_delete_warning

# Kept for callers/tests that still import the legacy name.
COLLECTION = LEGACY_COMPONENTS_COLLECTION

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


def ensure_component_indexes() -> dict[str, list[str]]:
    """Ensure indexes on typed CMDB collections (+ legacy source indexes)."""
    db = require_database()
    created = ensure_typed_cmdb_indexes(db)
    legacy = db[LEGACY_COMPONENTS_COLLECTION]
    legacy.create_index([("component_id", ASCENDING)], unique=True)
    legacy.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")
    created[LEGACY_COMPONENTS_COLLECTION] = ["component_id_1", "tenant_id_idx"]
    return created


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


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    return serialize_document(ensure_type_keys(doc))  # type: ignore[return-value]


def _find_scoped(
    component_id: str, *, tenant_id: str
) -> tuple[str, dict[str, Any]] | None:
    """Find a component in typed collections, then legacy fallback."""
    tid = require_tenant_id(tenant_id)
    db = require_database()
    scoped = tenant_filter(tid)
    hit = find_raw_across_typed(db, component_id, extra_filter=scoped)
    if hit is not None:
        return hit
    # Transitional adapter: unmigrated rows still readable via facade.
    legacy = db[LEGACY_COMPONENTS_COLLECTION].find_one(
        {"component_id": component_id, **scoped}
    )
    if legacy is not None:
        return LEGACY_COMPONENTS_COLLECTION, legacy
    return None


def get_component(component_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    require_tenant_id(tenant_id)
    hit = _find_scoped(component_id, tenant_id=tenant_id)
    if hit is None:
        return None
    _, doc = hit
    return _serialize(doc)


def create_component(payload: ComponentCreate, *, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    ensure_component_indexes()
    custom_fields_service.validate_component_custom_fields(
        payload.component_type, payload.custom_fields or {}, tenant_id=tid
    )
    component_id = payload.component_id or generate_component_id(payload.component_type)
    db = require_database()
    if component_id_taken(db, component_id):
        raise ComponentError(
            f"Component ID '{component_id}' already exists",
            status_code=409,
        )
    now = _now()
    doc = build_component_document(payload, component_id=component_id, now=now)
    stamp_tenant_id(doc, tenant_id=tid)
    coll = get_typed_collection(db, payload.component_type)
    try:
        coll.insert_one(doc)
    except DuplicateKeyError as exc:
        raise ComponentError(
            f"Component ID '{component_id}' already exists",
            status_code=409,
        ) from exc
    return _serialize(doc)


def update_component(
    component_id: str, payload: ComponentUpdate, *, tenant_id: str
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    hit = _find_scoped(component_id, tenant_id=tid)
    if hit is None:
        raise ComponentError(f"Component '{component_id}' not found", status_code=404)

    coll_name, existing = hit
    existing = ensure_type_keys(existing)
    try:
        updated = apply_component_update(existing, payload, now=_now())
    except ValueError as exc:
        raise ComponentError(str(exc), status_code=422) from exc

    ctype = ComponentType(updated["component_type"])
    custom_fields_service.validate_component_custom_fields(
        ctype, updated.get("custom_fields") or {}, tenant_id=tid
    )

    to_set = {k: v for k, v in updated.items() if k != "_id"}
    stamp_tenant_id(to_set, tenant_id=tid)
    target_name = collection_name_for_type(ctype)

    db = require_database()
    if coll_name == LEGACY_COMPONENTS_COLLECTION:
        # Promote on write: persist to typed collection and leave legacy copy.
        try:
            db[target_name].update_one(
                {"component_id": component_id},
                {"$set": to_set},
                upsert=True,
            )
        except DuplicateKeyError as exc:
            raise ComponentError(
                f"Component ID '{component_id}' already exists",
                status_code=409,
            ) from exc
    else:
        db[coll_name].update_one(
            {"component_id": component_id, **tenant_filter(tid)},
            {"$set": to_set},
        )
    return get_component(component_id, tenant_id=tid)  # type: ignore[return-value]


def delete_preview(component_id: str, *, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    doc = get_component(component_id, tenant_id=tid)
    if doc is None:
        raise ComponentError(f"Component '{component_id}' not found", status_code=404)
    warning = relationship_delete_warning(component_id, tenant_id=tid)
    return {
        "component": doc,
        "can_delete": True,
        "requires_confirmation": True,
        "relationship_warning": warning,
    }


def delete_component(
    component_id: str, *, confirmed: bool = False, tenant_id: str
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if not confirmed:
        raise ComponentError(
            "Deletion requires confirmation (set confirmed=true)",
            status_code=400,
        )
    preview = delete_preview(component_id, tenant_id=tid)
    db = require_database()
    deleted = 0
    for name in (*TYPED_CMDB_COLLECTIONS, LEGACY_COMPONENTS_COLLECTION):
        result = db[name].delete_one(
            {"component_id": component_id, **tenant_filter(tid)}
        )
        deleted += int(result.deleted_count)
    if deleted == 0:
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
    tenant_id: str,
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
    tid = require_tenant_id(tenant_id)
    ensure_component_indexes()
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

    base_query = _build_query(
        q=q,
        component_type=component_type,
        environment=environment,
        status=status,
        os_family=os_family,
        product_type=product_type,
    )
    query = merge_tenant_filter(base_query, tid)
    names = typed_collection_names(component_type)

    db = require_database()
    primary = names[0]
    match_stage = {"$match": query}
    pipeline: list[dict[str, Any]] = [match_stage]
    for other in names[1:]:
        pipeline.append(
            {"$unionWith": {"coll": other, "pipeline": [match_stage]}}
        )

    count_rows = list(db[primary].aggregate([*pipeline, {"$count": "total"}]))
    total = int(count_rows[0]["total"]) if count_rows else 0

    data_pipeline = [
        *pipeline,
        {"$sort": {sort_by: direction}},
        {"$skip": (page - 1) * page_size},
        {"$limit": page_size},
    ]
    items: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    for raw in db[primary].aggregate(data_pipeline):
        doc = _serialize(raw)
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
        "tenant_id": tid,
        "storage": "typed_cmdb",
        "collections": list(names),
    }


def as_view(doc: dict[str, Any]) -> ComponentView:
    return ComponentView.model_validate(doc)
