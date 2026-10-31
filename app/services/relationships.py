"""CMDB relationship persistence and delete-warning lookups.

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
from ..tenancy import stamp_tenant_id

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
    # Phase 4 prep: non-unique tenant_id (hard scoping in Phase 5).
    coll.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")
    return coll


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_relationship_id() -> str:
    return f"rel-{uuid.uuid4().hex[:12]}"


def _require_component(component_id: str, role: str) -> dict[str, Any]:
    # Lazy import avoids circular dependency with components.delete_preview
    from . import components as components_service

    doc = components_service.get_component(component_id)
    if doc is None:
        raise RelationshipError(
            f"Invalid {role} component_id '{component_id}' — component does not exist",
            status_code=422,
        )
    return doc


def _environment_mismatch_warning(
    source: dict[str, Any],
    target: dict[str, Any],
    relationship_environment: str | None,
) -> dict[str, Any] | None:
    source_env = (source.get("environment") or "").strip()
    target_env = (target.get("environment") or "").strip()
    warnings: list[str] = []
    if source_env and target_env and source_env.lower() != target_env.lower():
        warnings.append(
            f"Environment mismatch between components: source={source_env!r}, "
            f"target={target_env!r}."
        )
    if relationship_environment:
        rel_env = relationship_environment.strip()
        for label, env in (("source", source_env), ("target", target_env)):
            if env and rel_env.lower() != env.lower():
                warnings.append(
                    f"Relationship environment {rel_env!r} differs from {label} "
                    f"component environment {env!r}."
                )
    if not warnings:
        return None
    return {
        "code": "environment_mismatch",
        "messages": warnings,
    }


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def find_relationships_referencing(component_id: str) -> list[dict[str, Any]]:
    """Return relationships where component is source or target."""
    try:
        coll = _collection()
    except Exception:
        # DB unavailable — treat as no refs for delete preview soft path
        return []
    cursor = coll.find(
        {
            "$or": [
                {"source_component_id": component_id},
                {"target_component_id": component_id},
            ]
        }
    ).sort("updated_at", DESCENDING)
    return [serialize_document(doc) for doc in cursor]  # type: ignore[misc]


def relationship_delete_warning(component_id: str) -> dict[str, Any]:
    """Build the delete-warning payload for a component (wired for Phase 4)."""
    refs = find_relationships_referencing(component_id)
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


def get_relationship(relationship_id: str) -> dict[str, Any] | None:
    doc = _collection().find_one({"relationship_id": relationship_id})
    return serialize_document(doc)  # type: ignore[return-value]


def create_relationship(payload: RelationshipCreate) -> dict[str, Any]:
    source = _require_component(payload.source_component_id, "source")
    target = _require_component(payload.target_component_id, "target")

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
    )
    doc: dict[str, Any] = {
        "relationship_id": relationship_id,
        "source_component_id": payload.source_component_id,
        "target_component_id": payload.target_component_id,
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
    stamp_tenant_id(doc)
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


def update_relationship(relationship_id: str, payload: RelationshipUpdate) -> dict[str, Any]:
    coll = _collection()
    existing = coll.find_one({"relationship_id": relationship_id})
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
    if source_id == target_id:
        raise RelationshipError(
            "source_component_id and target_component_id cannot be the same",
            status_code=422,
        )

    source = _require_component(source_id, "source")
    target = _require_component(target_id, "target")

    fingerprint = duplicate_fingerprint(
        source_component_id=source_id,
        target_component_id=target_id,
        relationship_type=merged["relationship_type"],
        protocol=merged.get("protocol"),
        source_port=merged.get("source_port"),
        target_port=merged.get("target_port"),
    )
    data["duplicate_key"] = fingerprint
    data["updated_at"] = _now()

    try:
        coll.update_one({"relationship_id": relationship_id}, {"$set": data})
    except DuplicateKeyError as exc:
        raise RelationshipError(
            "Duplicate relationship: same source, target, type, protocol, "
            "source_port, and target_port already exist",
            status_code=409,
        ) from exc

    result = get_relationship(relationship_id)
    assert result is not None
    warning = _environment_mismatch_warning(source, target, result.get("environment"))
    if warning:
        result["warnings"] = [warning]
    return result


def delete_relationship(relationship_id: str) -> dict[str, Any]:
    result = _collection().delete_one({"relationship_id": relationship_id})
    if result.deleted_count == 0:
        raise RelationshipError(
            f"Relationship '{relationship_id}' not found",
            status_code=404,
        )
    return {"deleted": True, "relationship_id": relationship_id}


def list_relationships(
    *,
    q: str | None = None,
    source_component_id: str | None = None,
    target_component_id: str | None = None,
    component_id: str | None = None,
    relationship_type: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
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

    coll = _collection()
    total = coll.count_documents(query)
    cursor = (
        coll.find(query)
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
