"""Relationship lookups for CMDB delete warnings.

Phase 3 does **not** implement the relationship engine. This module provides the
hook used by delete confirmation so the UI can warn when relationships exist.
Until the engine lands, lookups return an empty list (soft-empty).
"""

from __future__ import annotations

from typing import Any


def find_relationships_referencing(component_id: str) -> list[dict[str, Any]]:
    """Return relationships that reference ``component_id``.

    Soft-empty in Phase 3 — ready for the future relationship engine.
    """
    _ = component_id  # reserved for Phase 4+ query
    return []


def relationship_delete_warning(component_id: str) -> dict[str, Any]:
    """Build the delete-warning payload for a component."""
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
        "engine_implemented": False,
    }
