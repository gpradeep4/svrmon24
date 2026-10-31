"""Relationship delete-warning hook (soft-empty until relationship engine)."""

from __future__ import annotations

from app.services.relationships import (
    find_relationships_referencing,
    relationship_delete_warning,
)


def test_find_relationships_soft_empty() -> None:
    assert find_relationships_referencing("srv-anything") == []


def test_delete_warning_payload_ready() -> None:
    warning = relationship_delete_warning("srv-1")
    assert warning["component_id"] == "srv-1"
    assert warning["has_relationships"] is False
    assert warning["relationship_count"] == 0
    assert warning["engine_ready"] is True
    assert warning["engine_implemented"] is False
    assert "No relationships" in warning["message"]
