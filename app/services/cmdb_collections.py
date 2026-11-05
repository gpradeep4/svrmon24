"""Typed CMDB collection routing (Master Phase 6).

Replaces the single polymorphic ``components`` collection with one Mongo
collection per component class while preserving the ``/api/components*``
facade and inventory UI.

Legacy ``components`` remains as a migration source (and transitional
read fallback) until operators confirm cutover.
"""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection
from pymongo.database import Database

from ..models.components import ComponentType

# Canonical typed collection names (master roadmap).
COLLECTION_SERVERS = "cmdb_servers"
COLLECTION_NETWORK = "cmdb_network"
COLLECTION_MIDDLEWARE = "cmdb_middleware"
COLLECTION_DATABASES = "cmdb_databases"
COLLECTION_APPLICATIONS = "cmdb_applications"

LEGACY_COMPONENTS_COLLECTION = "components"

TYPED_CMDB_COLLECTIONS: tuple[str, ...] = (
    COLLECTION_SERVERS,
    COLLECTION_NETWORK,
    COLLECTION_MIDDLEWARE,
    COLLECTION_DATABASES,
    COLLECTION_APPLICATIONS,
)

COLLECTION_BY_TYPE: dict[ComponentType, str] = {
    ComponentType.SERVER: COLLECTION_SERVERS,
    ComponentType.NETWORK: COLLECTION_NETWORK,
    ComponentType.MIDDLEWARE: COLLECTION_MIDDLEWARE,
    ComponentType.DATABASE: COLLECTION_DATABASES,
    ComponentType.APPLICATION: COLLECTION_APPLICATIONS,
}

TYPE_BY_COLLECTION: dict[str, ComponentType] = {
    name: ctype for ctype, name in COLLECTION_BY_TYPE.items()
}


def collection_name_for_type(component_type: ComponentType | str) -> str:
    """Return the typed Mongo collection for a component type."""
    if isinstance(component_type, str):
        component_type = ComponentType(component_type)
    return COLLECTION_BY_TYPE[component_type]


def typed_collection_names(
    component_type: ComponentType | str | None = None,
) -> tuple[str, ...]:
    """Collections to query for a list/get — one type or all typed."""
    if component_type is None:
        return TYPED_CMDB_COLLECTIONS
    return (collection_name_for_type(component_type),)


def ensure_typed_cmdb_indexes(db: Database) -> dict[str, list[str]]:
    """Create indexes on each typed CMDB collection.

    ``component_id`` stays **globally** unique in intent: each typed collection
    has a unique index, and the service layer also rejects collisions across
    collections (and the legacy ``components`` source during transition).
    """
    created: dict[str, list[str]] = {}
    for name in TYPED_CMDB_COLLECTIONS:
        coll = db[name]
        coll.create_index([("component_id", ASCENDING)], unique=True)
        coll.create_index([("tenant_id", ASCENDING)], name="tenant_id_idx")
        coll.create_index(
            [("tenant_id", ASCENDING), ("environment", ASCENDING)],
            name="tenant_environment_idx",
        )
        coll.create_index(
            [("tenant_id", ASCENDING), ("status", ASCENDING)],
            name="tenant_status_idx",
        )
        coll.create_index([("name", ASCENDING)])
        names = [
            "component_id_1",
            "tenant_id_idx",
            "tenant_environment_idx",
            "tenant_status_idx",
            "name_1",
        ]
        # Server-oriented hostname index (harmless on other types).
        coll.create_index([("hostname", ASCENDING)])
        names.append("hostname_1")
        created[name] = names
    return created


def get_typed_collection(db: Database, component_type: ComponentType | str) -> Collection:
    return db[collection_name_for_type(component_type)]


def find_raw_across_typed(
    db: Database,
    component_id: str,
    *,
    extra_filter: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Locate a document by ``component_id`` across typed collections.

    Returns ``(collection_name, raw_doc)`` or ``None``.
    """
    query: dict[str, Any] = {"component_id": component_id}
    if extra_filter:
        query = {**query, **extra_filter}
    for name in TYPED_CMDB_COLLECTIONS:
        doc = db[name].find_one(query)
        if doc is not None:
            return name, doc
    return None


def component_id_taken(db: Database, component_id: str) -> bool:
    """True if ``component_id`` exists in any typed collection or legacy source."""
    if find_raw_across_typed(db, component_id) is not None:
        return True
    return (
        db[LEGACY_COMPONENTS_COLLECTION].find_one(
            {"component_id": component_id}, {"_id": 1}
        )
        is not None
    )
