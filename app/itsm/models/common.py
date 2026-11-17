"""Shared ITSM enums and DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TICKET_TYPES: tuple[str, ...] = ("incident", "change", "problem")

INCIDENT_STATUSES: tuple[str, ...] = (
    "new",
    "in_progress",
    "on_hold",
    "resolved",
    "closed",
    "cancelled",
)

INCIDENT_PRIORITIES: tuple[str, ...] = ("p1", "p2", "p3", "p4")

# Allowed status transitions (from → to).
INCIDENT_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"in_progress", "on_hold", "cancelled"}),
    "in_progress": frozenset({"on_hold", "resolved", "cancelled"}),
    "on_hold": frozenset({"in_progress", "cancelled"}),
    "resolved": frozenset({"closed", "in_progress"}),
    "closed": frozenset(),
    "cancelled": frozenset(),
}

ACTIVITY_TYPES: tuple[str, ...] = (
    "created",
    "comment",
    "status_change",
    "assignment",
    "ci_link",
    "system",
)

TicketType = Literal["incident", "change", "problem"]
IncidentStatus = Literal[
    "new", "in_progress", "on_hold", "resolved", "closed", "cancelled"
]
IncidentPriority = Literal["p1", "p2", "p3", "p4"]
ActivityType = Literal[
    "created", "comment", "status_change", "assignment", "ci_link", "system"
]
ActivityVisibility = Literal["public", "internal"]


class CiLink(BaseModel):
    """Reference-only link to a CMDB component (same tenant)."""

    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(min_length=1, max_length=128)
    component_type: str | None = None
    name_snapshot: str | None = None
    table_key: str | None = None
    record_id: str | None = None


class TicketActivityCreate(BaseModel):
    """Append a comment / note to a ticket timeline."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=8000)
    activity_type: ActivityType = "comment"
    visibility: ActivityVisibility = "public"
