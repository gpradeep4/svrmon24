"""CMDB relationship persistence (tenant-scoped).

Manual entry only — no network scanning or hostname inference.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from ..db import require_database
from ..models.relationships import (
    RELATIONSHIP_TYPE_DOCS,
    RelationshipCreate,
    RelationshipType,
    RelationshipUpdate,
    duplicate_fingerprint,
    to_relationship_row,
)
from ..serialization import serialize_document
from ..tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id, tenant_filter

COLLECTION = "cmdb_relationships"


class RelationshipError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _collection() -> Collection:
    coll = require_database()[COLLECTION]
    coll.create_index([("relationship_id", ASCENDING)], unique=True)
    coll.create_index([("duplicate_key", ASCENDING)], unique=True)
    coll.create_index([("source_component_id", ASCENDING)])
    coll.create_index([("target_component_id", ASCENDING)])
    coll.create_index([("relationship_type", ASCENDING)])
    coll.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")
    return coll


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_relationship_id() -> str:
    return f"rel-{uuid.uuid4().hex[:12]}"


def _require_endpoint(
    entity_id: str,
    role: str,
    *,
    tenant_id: str,
    ref_table: str | None = None,
) -> dict[str, Any]:
    """Resolve a relationship endpoint as CMDB component or custom record."""
    from . import custom_tables as custom_tables_service
    from .custom_tables import CustomTableError

    try:
        return custom_tables_service.resolve_entity_ref(
            entity_id, ref_table, tenant_id=tenant_id, role=f"{role} endpoint"
        )
    except CustomTableError as exc:
        raise RelationshipError(exc.message, status_code=exc.status_code) from exc


def _environment_mismatch_warning(
    source: dict[str, Any],
    target: dict[str, Any],
    relationship_environment: str | None,
) -> dict[str, Any] | None:
    source_env = (source.get("environment") or "").strip()
    target_env = (target.get("environment") or "").strip()
    # Fall back to nested component env for CMDB endpoints.
    if not source_env and isinstance(source.get("component"), dict):
        source_env = (source["component"].get("environment") or "").strip()
    if not target_env and isinstance(target.get("component"), dict):
        target_env = (target["component"].get("environment") or "").strip()
    warnings: list[str] = []
    if source_env and target_env and source_env.lower() != target_env.lower():
        warnings.append(
            f"Environment mismatch between endpoints: source={source_env!r}, "
            f"target={target_env!r}."
        )
    if relationship_environment:
        rel_env = relationship_environment.strip()
        for label, env in (("source", source_env), ("target", target_env)):
            if env and rel_env.lower() != env.lower():
                warnings.append(
                    f"Relationship environment {rel_env!r} differs from {label} "
                    f"endpoint environment {env!r}."
                )
    if not warnings:
        return None
    return {
        "code": "environment_mismatch",
        "messages": warnings,
    }


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def find_relationships_referencing(
    component_id: str, *, tenant_id: str
) -> list[dict[str, Any]]:
    """Return relationships where component is source or target (same tenant)."""
    tid = require_tenant_id(tenant_id)
    try:
        coll = _collection()
    except Exception:
        return []
    cursor = coll.find(
        merge_tenant_filter(
            {
                "$or": [
                    {"source_component_id": component_id},
                    {"target_component_id": component_id},
                ]
            },
            tid,
        )
    ).sort("updated_at", DESCENDING)
    return [serialize_document(doc) for doc in cursor]  # type: ignore[misc]


def relationship_delete_warning(
    component_id: str, *, tenant_id: str
) -> dict[str, Any]:
    """Build the delete-warning payload for a component."""
    refs = find_relationships_referencing(component_id, tenant_id=tenant_id)
    return {
        "component_id": component_id,
        "has_relationships": len(refs) > 0,
        "relationship_count": len(refs),
        "relationships": refs,
        "message": (
            f"Component {component_id} is referenced by {len(refs)} relationship(s). "
            "Deleting it may orphan dependency links."
            if refs
            else f"No relationships currently reference {component_id}."
        ),
        "engine_ready": True,
        "engine_implemented": True,
    }


def get_relationship(relationship_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _collection().find_one(
        {"relationship_id": relationship_id, **tenant_filter(tid)}
    )
    return serialize_document(doc)  # type: ignore[return-value]


def create_relationship(
    payload: RelationshipCreate, *, tenant_id: str
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    source = _require_endpoint(
        payload.source_component_id,
        "source",
        tenant_id=tid,
        ref_table=payload.source_table,
    )
    target = _require_endpoint(
        payload.target_component_id,
        "target",
        tenant_id=tid,
        ref_table=payload.target_table,
    )
    source_table = source.get("ref_table") if source.get("kind") == "custom" else (
        payload.source_table or source.get("ref_table")
    )
    target_table = target.get("ref_table") if target.get("kind") == "custom" else (
        payload.target_table or target.get("ref_table")
    )
    # Persist null for plain CMDB-only edges when caller omitted table (compat).
    if source.get("kind") == "component" and not payload.source_table:
        source_table = None
    if target.get("kind") == "component" and not payload.target_table:
        target_table = None

    relationship_id = payload.relationship_id or generate_relationship_id()
    now = _now()
    rel_type = payload.relationship_type.value
    fingerprint = duplicate_fingerprint(
        source_component_id=payload.source_component_id,
        target_component_id=payload.target_component_id,
        relationship_type=rel_type,
        protocol=payload.protocol,
        source_port=payload.source_port,
        target_port=payload.target_port,
        source_table=source_table,
        target_table=target_table,
    )
    doc: dict[str, Any] = {
        "relationship_id": relationship_id,
        "source_component_id": payload.source_component_id,
        "target_component_id": payload.target_component_id,
        "source_table": source_table,
        "target_table": target_table,
        "relationship_type": rel_type,
        "protocol": payload.protocol,
        "source_port": payload.source_port,
        "target_port": payload.target_port,
        "url_or_path": payload.url_or_path,
        "environment": payload.environment,
        "discovery_method": payload.discovery_method.value,
        "verification_status": payload.verification_status.value,
        "confidence": payload.confidence.value,
        "evidence_or_notes": payload.evidence_or_notes,
        "duplicate_key": fingerprint,
        "created_at": now,
        "updated_at": now,
    }
    stamp_tenant_id(doc, tenant_id=tid)
    try:
        _collection().insert_one(doc)
    except DuplicateKeyError as exc:
        raise RelationshipError(
            "Duplicate relationship: same source, target, type, protocol, "
            "source_port, and target_port already exist",
            status_code=409,
        ) from exc

    result = serialize_document(doc)
    assert result is not None
    warning = _environment_mismatch_warning(source, target, payload.environment)
    if warning:
        result["warnings"] = [warning]
    return result


def update_relationship(
    relationship_id: str, payload: RelationshipUpdate, *, tenant_id: str
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    coll = _collection()
    existing = coll.find_one(
        {"relationship_id": relationship_id, **tenant_filter(tid)}
    )
    if existing is None:
        raise RelationshipError(
            f"Relationship '{relationship_id}' not found",
            status_code=404,
        )

    data = payload.model_dump(exclude_unset=True)
    for key in (
        "relationship_type",
        "discovery_method",
        "verification_status",
        "confidence",
    ):
        if key in data and data[key] is not None:
            data[key] = _enum_value(data[key])

    merged = {**existing, **data}
    source_id = merged["source_component_id"]
    target_id = merged["target_component_id"]
    source_table = merged.get("source_table")
    target_table = merged.get("target_table")
    if source_id == target_id and (source_table or "") == (target_table or ""):
        raise RelationshipError(
            "source and target cannot be the same entity (same id and table)",
            status_code=422,
        )

    source = _require_endpoint(
        source_id, "source", tenant_id=tid, ref_table=source_table
    )
    target = _require_endpoint(
        target_id, "target", tenant_id=tid, ref_table=target_table
    )
    if source.get("kind") == "custom":
        source_table = source.get("ref_table")
        data["source_table"] = source_table
    if target.get("kind") == "custom":
        target_table = target.get("ref_table")
        data["target_table"] = target_table

    fingerprint = duplicate_fingerprint(
        source_component_id=source_id,
        target_component_id=target_id,
        relationship_type=merged["relationship_type"],
        protocol=merged.get("protocol"),
        source_port=merged.get("source_port"),
        target_port=merged.get("target_port"),
        source_table=source_table,
        target_table=target_table,
    )
    data["duplicate_key"] = fingerprint
    data["updated_at"] = _now()
    stamp_tenant_id(data, tenant_id=tid)

    try:
        coll.update_one(
            {"relationship_id": relationship_id, **tenant_filter(tid)},
            {"$set": data},
        )
    except DuplicateKeyError as exc:
        raise RelationshipError(
            "Duplicate relationship: same source, target, type, protocol, "
            "source_port, and target_port already exist",
            status_code=409,
        ) from exc

    result = get_relationship(relationship_id, tenant_id=tid)
    assert result is not None
    warning = _environment_mismatch_warning(source, target, result.get("environment"))
    if warning:
        result["warnings"] = [warning]
    return result


def delete_relationship(relationship_id: str, *, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    result = _collection().delete_one(
        {"relationship_id": relationship_id, **tenant_filter(tid)}
    )
    if result.deleted_count == 0:
        raise RelationshipError(
            f"Relationship '{relationship_id}' not found",
            status_code=404,
        )
    return {"deleted": True, "relationship_id": relationship_id}


def list_relationships(
    *,
    tenant_id: str,
    q: str | None = None,
    source_component_id: str | None = None,
    target_component_id: str | None = None,
    component_id: str | None = None,
    relationship_type: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    query: dict[str, Any] = {}

    if source_component_id:
        query["source_component_id"] = source_component_id
    if target_component_id:
        query["target_component_id"] = target_component_id
    if component_id:
        query["$or"] = [
            {"source_component_id": component_id},
            {"target_component_id": component_id},
        ]
    if relationship_type:
        if relationship_type not in {t.value for t in RelationshipType}:
            raise RelationshipError(
                f"Invalid relationship_type: {relationship_type}",
                status_code=422,
            )
        query["relationship_type"] = relationship_type
    if q:
        import re

        pattern = re.compile(re.escape(q.strip()), re.IGNORECASE)
        text_or = [
            {"relationship_id": pattern},
            {"source_component_id": pattern},
            {"target_component_id": pattern},
            {"protocol": pattern},
            {"url_or_path": pattern},
            {"evidence_or_notes": pattern},
        ]
        if "$or" in query:
            query = {"$and": [{"$or": query["$or"]}, {"$or": text_or}]}
        else:
            query["$or"] = text_or

    scoped = merge_tenant_filter(query, tid)
    coll = _collection()
    total = coll.count_documents(scoped)
    cursor = (
        coll.find(scoped)
        .sort("updated_at", DESCENDING)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for raw in cursor:
        doc = serialize_document(raw)
        assert doc is not None
        items.append(doc)
        rows.append(to_relationship_row(doc))

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "items": items,
        "rows": rows,
        "tenant_id": tid,
    }


def relationship_type_catalog() -> dict[str, Any]:
    return {
        "types": [
            {
                "relationship_type": key,
                **meta,
            }
            for key, meta in RELATIONSHIP_TYPE_DOCS.items()
        ]
    }
