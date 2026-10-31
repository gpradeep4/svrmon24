"""Relationship model validation — ports independent, self-ref rejected."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.relationships import (
    RelationshipCreate,
    RelationshipType,
    to_relationship_row,
)


def test_ports_independent_on_create() -> None:
    payload = RelationshipCreate(
        source_component_id="a",
        target_component_id="b",
        relationship_type=RelationshipType.CONNECTS_TO,
        protocol="TCP",
        source_port=1234,
        target_port=443,
    )
    assert payload.source_port == 1234
    assert payload.target_port == 443


def test_blank_port_strings_become_none() -> None:
    payload = RelationshipCreate.model_validate(
        {
            "source_component_id": "a",
            "target_component_id": "b",
            "relationship_type": "DEPENDS_ON",
            "source_port": "",
            "target_port": "  ",
        }
    )
    assert payload.source_port is None
    assert payload.target_port is None


def test_invalid_port_range() -> None:
    with pytest.raises(ValidationError):
        RelationshipCreate(
            source_component_id="a",
            target_component_id="b",
            relationship_type=RelationshipType.CONNECTS_TO,
            source_port=70000,
        )


def test_self_reference_model_error() -> None:
    with pytest.raises(ValidationError):
        RelationshipCreate(
            source_component_id="same",
            target_component_id="same",
            relationship_type=RelationshipType.DEPENDS_ON,
        )


def test_row_keeps_port_columns_separate() -> None:
    row = to_relationship_row(
        {
            "relationship_id": "rel-1",
            "source_component_id": "a",
            "target_component_id": "b",
            "relationship_type": "CONNECTS_TO",
            "protocol": "HTTPS",
            "source_port": None,
            "target_port": 8443,
        }
    )
    assert row["protocol"] == "HTTPS"
    assert row["source_port"] == "—"
    assert row["target_port"] == "8443"
    assert "ports" not in row
