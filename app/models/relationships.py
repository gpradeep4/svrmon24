"""CMDB relationship models — manual full-stack dependency links."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RelationshipType(str, Enum):
    """Relationship types with explicit direction: source → target.

    - HOSTED_ON: source is hosted on target (e.g. Middleware → Server).
      One server can be the target of many HOSTED_ON edges.
    - DEPENDS_ON: source depends on target to function.
    - CONNECTS_TO: source opens a connection to target.
    - ROUTES_TO: source routes/forwards traffic to target.
    """

    HOSTED_ON = "HOSTED_ON"
    DEPENDS_ON = "DEPENDS_ON"
    CONNECTS_TO = "CONNECTS_TO"
    ROUTES_TO = "ROUTES_TO"


RELATIONSHIP_TYPE_DOCS: dict[str, dict[str, str]] = {
    RelationshipType.HOSTED_ON.value: {
        "direction": "source → target",
        "meaning": "Source component is hosted/runs on the target component.",
        "example": "Middleware mware-1 HOSTED_ON Server srv-1",
    },
    RelationshipType.DEPENDS_ON.value: {
        "direction": "source → target",
        "meaning": "Source depends on target to operate (runtime or config dependency).",
        "example": "Application app-1 DEPENDS_ON Database db-1",
    },
    RelationshipType.CONNECTS_TO.value: {
        "direction": "source → target",
        "meaning": "Source initiates or maintains a connection to target.",
        "example": "Middleware mware-1 CONNECTS_TO Database db-1",
    },
    RelationshipType.ROUTES_TO.value: {
        "direction": "source → target",
        "meaning": "Source routes or forwards traffic to target.",
        "example": "Network net-lb ROUTES_TO Application app-1",
    },
}


class DiscoveryMethod(str, Enum):
    MANUALLY_CONFIGURED = "manually_configured"
    DISCOVERED = "discovered"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _normalize_port(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned == "":
            return None
        if not cleaned.isdigit():
            raise ValueError("port must be an integer between 1 and 65535")
        value = int(cleaned)
    if isinstance(value, bool):
        raise ValueError("port must be an integer between 1 and 65535")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int):
        raise ValueError("port must be an integer between 1 and 65535")
    if value < 1 or value > 65535:
        raise ValueError("port must be between 1 and 65535")
    return value


class RelationshipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship_id: str | None = Field(default=None, min_length=1, max_length=128)
    source_component_id: str = Field(min_length=1, max_length=128)
    target_component_id: str = Field(min_length=1, max_length=128)
    relationship_type: RelationshipType
    protocol: str | None = Field(default=None, max_length=64)
    source_port: int | None = None
    target_port: int | None = None
    url_or_path: str | None = Field(default=None, max_length=1024)
    environment: str | None = Field(default=None, max_length=128)
    discovery_method: DiscoveryMethod = DiscoveryMethod.MANUALLY_CONFIGURED
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    evidence_or_notes: str | None = Field(default=None, max_length=4000)

    @field_validator("relationship_id", "source_component_id", "target_component_id")
    @classmethod
    def strip_ids(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be blank")
        return cleaned

    @field_validator("protocol", "url_or_path", "environment", "evidence_or_notes")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("source_port", "target_port", mode="before")
    @classmethod
    def validate_ports(cls, value: Any) -> int | None:
        return _normalize_port(value)

    @model_validator(mode="after")
    def reject_self_reference(self) -> RelationshipCreate:
        if self.source_component_id == self.target_component_id:
            raise ValueError("source_component_id and target_component_id cannot be the same")
        return self


class RelationshipUpdate(BaseModel):
    """Partial update. Endpoint IDs and type may change but are re-validated."""

    model_config = ConfigDict(extra="forbid")

    source_component_id: str | None = Field(default=None, min_length=1, max_length=128)
    target_component_id: str | None = Field(default=None, min_length=1, max_length=128)
    relationship_type: RelationshipType | None = None
    protocol: str | None = None
    source_port: int | None = None
    target_port: int | None = None
    url_or_path: str | None = None
    environment: str | None = None
    discovery_method: DiscoveryMethod | None = None
    verification_status: VerificationStatus | None = None
    confidence: ConfidenceLevel | None = None
    evidence_or_notes: str | None = None

    @field_validator("source_component_id", "target_component_id")
    @classmethod
    def strip_ids(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be blank")
        return cleaned

    @field_validator("protocol", "url_or_path", "environment", "evidence_or_notes")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("source_port", "target_port", mode="before")
    @classmethod
    def validate_ports(cls, value: Any) -> int | None:
        # Allow explicit null to clear a port; distinguish unset via exclude_unset
        return _normalize_port(value)


class RelationshipView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    relationship_id: str
    source_component_id: str
    target_component_id: str
    relationship_type: RelationshipType
    protocol: str | None = None
    source_port: int | None = None
    target_port: int | None = None
    url_or_path: str | None = None
    environment: str | None = None
    discovery_method: DiscoveryMethod
    verification_status: VerificationStatus
    confidence: ConfidenceLevel
    evidence_or_notes: str | None = None
    created_at: datetime
    updated_at: datetime


def display_port(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


def to_relationship_row(doc: dict[str, Any]) -> dict[str, Any]:
    """Table row with Protocol / Source Port / Target Port as separate columns."""
    return {
        "relationship_id": doc.get("relationship_id"),
        "source_component_id": doc.get("source_component_id"),
        "target_component_id": doc.get("target_component_id"),
        "relationship_type": doc.get("relationship_type"),
        "protocol": doc.get("protocol") or "—",
        "source_port": display_port(doc.get("source_port")),
        "target_port": display_port(doc.get("target_port")),
        "url_or_path": doc.get("url_or_path") or "—",
        "environment": doc.get("environment") or "—",
        "discovery_method": doc.get("discovery_method"),
        "verification_status": doc.get("verification_status"),
        "confidence": doc.get("confidence"),
    }


def duplicate_fingerprint(
    *,
    source_component_id: str,
    target_component_id: str,
    relationship_type: str,
    protocol: str | None,
    source_port: int | None,
    target_port: int | None,
) -> str:
    """Stable key for duplicate detection (ports remain independent fields)."""
    return "|".join(
        [
            source_component_id,
            target_component_id,
            relationship_type,
            (protocol or "").lower(),
            "" if source_port is None else str(source_port),
            "" if target_port is None else str(target_port),
        ]
    )
