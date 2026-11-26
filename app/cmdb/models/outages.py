"""CMDB CI Outage models (Outage Information tab — C4).

``itsm_ref`` is an optional deep link to related Incident/Change — tickets
remain in ITSM; CMDB never joins across databases.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .work_info import ItsmTicketRef


class OutageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unavailability_class: str = Field(default="planned", min_length=1, max_length=80)
    unavailability_type: str = Field(default="maintenance", min_length=1, max_length=80)
    status: str = Field(default="scheduled", min_length=1, max_length=40)
    assignment_status: str | None = Field(default=None, max_length=80)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    summary: str = Field(min_length=1, max_length=500)
    itsm_ref: ItsmTicketRef | None = None

    @field_validator(
        "unavailability_class",
        "unavailability_type",
        "status",
        "summary",
    )
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("assignment_status")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class OutageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unavailability_class: str | None = Field(default=None, min_length=1, max_length=80)
    unavailability_type: str | None = Field(default=None, min_length=1, max_length=80)
    status: str | None = Field(default=None, min_length=1, max_length=40)
    assignment_status: str | None = Field(default=None, max_length=80)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    summary: str | None = Field(default=None, min_length=1, max_length=500)
    itsm_ref: ItsmTicketRef | None = None

    @field_validator(
        "unavailability_class",
        "unavailability_type",
        "status",
        "summary",
    )
    @classmethod
    def _strip_optional_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("assignment_status")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


def to_outage_row(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "outage_id": doc.get("outage_id"),
        "tenant_id": doc.get("tenant_id"),
        "component_id": doc.get("component_id"),
        "unavailability_class": doc.get("unavailability_class"),
        "unavailability_type": doc.get("unavailability_type"),
        "status": doc.get("status"),
        "assignment_status": doc.get("assignment_status"),
        "starts_at": doc.get("starts_at"),
        "ends_at": doc.get("ends_at"),
        "summary": doc.get("summary"),
        "itsm_ref": doc.get("itsm_ref"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }
