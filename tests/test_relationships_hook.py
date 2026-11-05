"""Relationship delete-warning hook (tenant-scoped)."""

from __future__ import annotations

from app.services.relationships import relationship_delete_warning
from app.tenancy import MIGRATION_TENANT_ID


def test_delete_warning_payload_ready_when_empty(clean_db) -> None:
    warning = relationship_delete_warning(
        "srv-no-links", tenant_id=MIGRATION_TENANT_ID
    )
    assert warning["component_id"] == "srv-no-links"
    assert warning["has_relationships"] is False
    assert warning["relationship_count"] == 0
    assert warning["engine_ready"] is True
    assert warning["engine_implemented"] is True
    assert "No relationships" in warning["message"]
