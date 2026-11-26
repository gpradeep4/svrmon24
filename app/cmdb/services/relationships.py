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

from ...db import require_database
from ..models.relationships import (
    PARENT_IS_SOURCE_TYPES,
    PARENT_IS_TARGET_TYPES,
    RELATIONSHIP_TYPE_DOCS,
    RelationshipCreate,
    RelationshipType,
    RelationshipUpdate,
    duplicate_fingerprint,
    to_relationship_row,
)
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id, tenant_filter

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
    # Entitlements-only gate (no payment system). Unlimited by default in v1.
    from ...services import entitlements as entitlements_service
    from ...services.entitlements import EntitlementError

    try:
        entitlements_service.assert_can_create_relationship(tid)
    except EntitlementError as exc:
        raise RelationshipError(exc.message, status_code=exc.status_code) from exc

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


def _validate_relationship_type(relationship_type: str | None) -> str | None:
    if not relationship_type:
        return None
    if relationship_type not in {t.value for t in RelationshipType}:
        raise RelationshipError(
            f"Invalid relationship_type: {relationship_type}",
            status_code=422,
        )
    return relationship_type


def _direction_match_clause(
    component_id: str,
    direction: str,
    relationship_type: str | None = None,
) -> dict[str, Any]:
    """Build Mongo clause for Show: Child / Parent.

    - child: this CI is parent (HOSTS source; HOSTED_ON target; other types as source)
    - parent: inverse
    - both: this CI is source or target
    """
    direction_norm = (direction or "both").strip().lower()
    if direction_norm not in {"child", "parent", "both"}:
        raise RelationshipError(
            "direction must be child, parent, or both",
            status_code=422,
        )
    if direction_norm == "both":
        return {
            "$or": [
                {"source_component_id": component_id},
                {"target_component_id": component_id},
            ]
        }

    want_child = direction_norm == "child"
    all_types = {t.value for t in RelationshipType}
    if relationship_type:
        type_set = {relationship_type}
    else:
        type_set = all_types

    clauses: list[dict[str, Any]] = []
    for rtype in sorted(type_set):
        if rtype in PARENT_IS_SOURCE_TYPES:
            # HOSTS: parent=source → child filter matches source=component_id
            if want_child:
                clauses.append(
                    {"source_component_id": component_id, "relationship_type": rtype}
                )
            else:
                clauses.append(
                    {"target_component_id": component_id, "relationship_type": rtype}
                )
        elif rtype in PARENT_IS_TARGET_TYPES:
            # HOSTED_ON: parent=target → child filter matches target=component_id
            if want_child:
                clauses.append(
                    {"target_component_id": component_id, "relationship_type": rtype}
                )
            else:
                clauses.append(
                    {"source_component_id": component_id, "relationship_type": rtype}
                )
        else:
            # Conventional graph: child view = outgoing (source), parent = incoming
            if want_child:
                clauses.append(
                    {"source_component_id": component_id, "relationship_type": rtype}
                )
            else:
                clauses.append(
                    {"target_component_id": component_id, "relationship_type": rtype}
                )

    if not clauses:
        return {"relationship_id": {"$exists": False}}  # match nothing
    if len(clauses) == 1:
        return clauses[0]
    return {"$or": clauses}


def _related_endpoint(
    edge: dict[str, Any], focus_component_id: str
) -> tuple[str, str | None]:
    """Return (related_id, related_table) for the non-focus end of an edge."""
    if edge.get("source_component_id") == focus_component_id:
        return edge.get("target_component_id") or "", edge.get("target_table")
    return edge.get("source_component_id") or "", edge.get("source_table")


def _component_summary(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    return {
        "component_id": doc.get("component_id"),
        "name": doc.get("name"),
        "component_type": doc.get("component_type"),
        "status": doc.get("status"),
        "environment": doc.get("environment"),
        "device_type": doc.get("device_type"),
        "management_ip": doc.get("management_ip"),
        "virtual_ip": doc.get("virtual_ip"),
        "application_name": doc.get("application_name"),
        "application_type": doc.get("application_type"),
        "product_type": doc.get("product_type"),
        "product_version": doc.get("product_version"),
        "os_family": doc.get("os_family"),
        "os_version": doc.get("os_version"),
        "hostname": doc.get("hostname"),
        "ip_address": doc.get("ip_address"),
    }


def _enrich_edge(edge: dict[str, Any], *, focus_component_id: str, tenant_id: str) -> dict[str, Any]:
    from . import components as components_service

    related_id, related_table = _related_endpoint(edge, focus_component_id)
    related_doc = None
    if related_id and not related_table:
        related_doc = components_service.get_component(related_id, tenant_id=tenant_id)
    enriched = dict(edge)
    enriched["related_component_id"] = related_id or None
    enriched["related_table"] = related_table
    enriched["related_component"] = _component_summary(related_doc)
    # display helpers
    rel = enriched.get("related_component") or {}
    enriched["related_name"] = rel.get("name") or related_id
    enriched["related_category"] = rel.get("component_type") or related_table or "—"
    enriched["related_product"] = (
        rel.get("application_name")
        or rel.get("product_type")
        or rel.get("device_type")
        or rel.get("os_family")
        or "—"
    )
    enriched["related_version"] = (
        rel.get("product_version") or rel.get("os_version") or "—"
    )
    return enriched


def list_relationships(
    *,
    tenant_id: str,
    q: str | None = None,
    source_component_id: str | None = None,
    target_component_id: str | None = None,
    component_id: str | None = None,
    relationship_type: str | None = None,
    direction: str | None = None,
    page: int = 1,
    page_size: int = 25,
    enrich: bool = False,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    query: dict[str, Any] = {}
    relationship_type = _validate_relationship_type(relationship_type)
    direction_norm = (direction or "").strip().lower() or None

    if direction_norm and not component_id:
        raise RelationshipError(
            "direction requires component_id",
            status_code=422,
        )

    if source_component_id:
        query["source_component_id"] = source_component_id
    if target_component_id:
        query["target_component_id"] = target_component_id

    if component_id and direction_norm and direction_norm != "both":
        # Direction clause already scopes type when provided.
        dir_clause = _direction_match_clause(
            component_id, direction_norm, relationship_type
        )
        query = {**query, **dir_clause} if not query else {"$and": [query, dir_clause]}
        # relationship_type already embedded in direction clauses when set
        relationship_type_applied = True
    elif component_id:
        query["$or"] = [
            {"source_component_id": component_id},
            {"target_component_id": component_id},
        ]
        relationship_type_applied = False
    else:
        relationship_type_applied = False

    if relationship_type and not relationship_type_applied:
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
        if "$or" in query or "$and" in query:
            query = {"$and": [query, {"$or": text_or}]}
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
        if enrich and component_id:
            doc = _enrich_edge(doc, focus_component_id=component_id, tenant_id=tid)
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
        "direction": direction_norm or "both",
        "component_id": component_id,
    }


def _classify_related_group(summary: dict[str, Any] | None, *, synthetic: str | None = None) -> str:
    if synthetic:
        return synthetic
    if not summary:
        return "product"
    ctype = (summary.get("component_type") or "").strip()
    device_type = (summary.get("device_type") or "").strip().lower()
    app_type = (summary.get("application_type") or "").strip().lower()
    name = (summary.get("name") or "").strip().lower()
    product = (summary.get("product_type") or "").strip().lower()

    if ctype == "Network" or device_type in {
        "ip_endpoint",
        "ip",
        "ip address",
        "access_point",
    }:
        return "ip_endpoint"
    if (
        app_type in {"os", "operating_system", "operating system"}
        or "operating system" in name
        or name.endswith(" os")
        or product in {"os", "operating_system"}
    ):
        return "operating_system"
    if "processor" in name or "cpu" in device_type or app_type == "processor":
        return "processor"
    return "product"


TREE_GROUP_META: list[dict[str, str]] = [
    {"key": "ip_endpoint", "label": "IP Endpoint"},
    {"key": "operating_system", "label": "Operating System"},
    {"key": "processor", "label": "Processor"},
    {"key": "product", "label": "Product"},
]


def relationship_details(
    component_id: str, *, tenant_id: str
) -> dict[str, Any]:
    """Projection: tree grouped by related CI class + detail items (C2)."""
    from . import components as components_service

    tid = require_tenant_id(tenant_id)
    focus = components_service.get_component(component_id, tenant_id=tid)
    if focus is None:
        raise RelationshipError(
            f"Component '{component_id}' not found",
            status_code=404,
        )

    listed = list_relationships(
        tenant_id=tid,
        component_id=component_id,
        direction="child",
        page=1,
        page_size=200,
        enrich=True,
    )

    groups: dict[str, dict[str, Any]] = {
        meta["key"]: {"key": meta["key"], "label": meta["label"], "total": 0, "items": []}
        for meta in TREE_GROUP_META
    }

    seen_related: set[str] = set()
    for edge in listed["items"]:
        related_id = edge.get("related_component_id") or ""
        summary = edge.get("related_component")
        group_key = _classify_related_group(summary)
        item = {
            "relationship_id": edge.get("relationship_id"),
            "relationship_type": edge.get("relationship_type"),
            "component_id": related_id,
            "name": edge.get("related_name") or related_id,
            "component_type": (summary or {}).get("component_type"),
            "category": edge.get("related_category"),
            "product": edge.get("related_product"),
            "version": edge.get("related_version"),
            "device_type": (summary or {}).get("device_type"),
            "management_ip": (summary or {}).get("management_ip"),
            "virtual_ip": (summary or {}).get("virtual_ip"),
            "status": (summary or {}).get("status"),
            "environment": (summary or {}).get("environment"),
            "detail": summary,
        }
        groups[group_key]["items"].append(item)
        groups[group_key]["total"] += 1
        if related_id:
            seen_related.add(related_id)

    # Optional OS summary node from Server os_* (dual representation).
    if focus.get("component_type") == "Server" and (
        focus.get("os_family") or focus.get("os_version")
    ):
        os_label = " ".join(
            p
            for p in [focus.get("os_family"), focus.get("os_version")]
            if p
        ).strip() or "Operating System"
        # Only add synthetic if no dedicated OS child already mirrors it.
        already = any(
            (it.get("name") or "").lower() == os_label.lower()
            for it in groups["operating_system"]["items"]
        )
        if not already:
            groups["operating_system"]["items"].insert(
                0,
                {
                    "relationship_id": None,
                    "relationship_type": None,
                    "component_id": component_id,
                    "name": os_label,
                    "component_type": "Server",
                    "category": "Operating System",
                    "product": focus.get("os_family") or "—",
                    "version": focus.get("os_version") or "—",
                    "synthetic": True,
                    "status": focus.get("status"),
                    "environment": focus.get("environment"),
                    "detail": {
                        "os_family": focus.get("os_family"),
                        "os_version": focus.get("os_version"),
                        "hostname": focus.get("hostname"),
                    },
                },
            )
            groups["operating_system"]["total"] = len(groups["operating_system"]["items"])

    tree = [
        {
            "key": meta["key"],
            "label": meta["label"],
            "count": groups[meta["key"]]["total"],
        }
        for meta in TREE_GROUP_META
    ]

    return {
        "component_id": component_id,
        "name": focus.get("name"),
        "component_type": focus.get("component_type"),
        "primary_ip_address": focus.get("ip_address"),
        "tree": tree,
        "groups": groups,
        "child_relationship_total": listed["total"],
        "related_component_ids": sorted(seen_related),
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
