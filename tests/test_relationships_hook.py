"""Relationship delete-warning hook (Phase 4 — engine implemented)."""

from __future__ import annotations

from app.services.relationships import relationship_delete_warning


def test_delete_warning_payload_ready_when_empty(clean_db) -> None:
    warning = relationship_delete_warning("srv-no-links")
    assert warning["component_id"] == "srv-no-links"
    assert warning["has_relationships"] is False
    assert warning["relationship_count"] == 0
    assert warning["engine_ready"] is True
    assert warning["engine_implemented"] is True
    assert "No relationships" in warning["message"]
