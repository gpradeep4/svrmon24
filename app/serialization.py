"""MongoDB ObjectId and BSON-friendly JSON serialization helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId


def serialize_value(value: Any) -> Any:
    """Recursively convert MongoDB/BSON types into JSON-safe values."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: serialize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    if isinstance(value, tuple):
        return [serialize_value(item) for item in value]
    return value


def serialize_document(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """Serialize a MongoDB document for API responses."""
    if document is None:
        return None
    return serialize_value(document)


def parse_object_id(value: str) -> ObjectId:
    """Parse a hex string into ObjectId or raise ValueError."""
    try:
        return ObjectId(value)
    except (InvalidId, TypeError) as exc:
        raise ValueError(f"Invalid ObjectId: {value!r}") from exc
