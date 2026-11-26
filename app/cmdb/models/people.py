"""CMDB CI People / support-group link models (People tab — C3)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PartyType(str, Enum):
    SUPPORT_GROUP = "support_group"
    PERSON = "person"


# Well-known roles; free-string still accepted for tenant-specific labels.
KNOWN_PEOPLE_ROLES: frozenset[str] = frozenset(
    {
        "managed_by",
        "supported_by",
        "owned_by",
        "approved_by",
    }
)


class PeopleLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party_type: PartyType
    party_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=300)
    role: str = Field(default="managed_by", min_length=1, max_length=100)
    primary_contact: bool = False
    notify_on_unavailability: bool = False
    assignment_enabled: bool = False
    access_permission: bool = False

    @field_validator("party_id", "display_name", "role")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned


class PeopleLinkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party_type: PartyType | None = None
    party_id: str | None = Field(default=None, min_length=1, max_length=200)
    display_name: str | None = Field(default=None, min_length=1, max_length=300)
    role: str | None = Field(default=None, min_length=1, max_length=100)
    primary_contact: bool | None = None
    notify_on_unavailability: bool | None = None
    assignment_enabled: bool | None = None
    access_permission: bool | None = None

    @field_validator("party_id", "display_name", "role")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned


def to_people_row(doc: dict[str, Any]) -> dict[str, Any]:
    """Public people-link row (no Mongo ``_id``)."""
    return {
        "link_id": doc.get("link_id"),
        "tenant_id": doc.get("tenant_id"),
        "component_id": doc.get("component_id"),
        "party_type": doc.get("party_type"),
        "party_id": doc.get("party_id"),
        "display_name": doc.get("display_name"),
        "role": doc.get("role"),
        "primary_contact": bool(doc.get("primary_contact")),
        "notify_on_unavailability": bool(doc.get("notify_on_unavailability")),
        "assignment_enabled": bool(doc.get("assignment_enabled")),
        "access_permission": bool(doc.get("access_permission")),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


# Type alias for API docs / frontend contracts.
PeopleRole = Literal["managed_by", "supported_by", "owned_by", "approved_by"] | str
