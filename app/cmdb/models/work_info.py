"""CMDB CI Work Info models (Work Info tab — C3).

Attachments live in ``cmdb_ci_attachments`` as MongoDB Binary blobs in the
CMDB database (same pattern as ITSM ticket attachments). No object-store
dependency; size/type caps enforced in the service layer.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WorkInfoType(str, Enum):
    GENERAL = "general"
    CUSTOMER_COMMUNICATION = "customer_communication"
    INCIDENT = "incident"
    PROBLEM = "problem"
    CHANGE = "change"
    NOTE = "note"
    OTHER = "other"


class ViewAccess(str, Enum):
    INTERNAL = "internal"
    PUBLIC = "public"


class ItsmTicketRef(BaseModel):
    """Optional deep-link only — tickets stay in ITSM DB; never joined from CMDB."""

    model_config = ConfigDict(extra="forbid")

    module: str = Field(min_length=1, max_length=40)
    ticket_id: str = Field(min_length=1, max_length=80)

    @field_validator("module", "ticket_id")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("module")
    @classmethod
    def _module_known(cls, value: str) -> str:
        allowed = {"incident", "change", "problem"}
        low = value.lower()
        if low not in allowed:
            raise ValueError(f"module must be one of {sorted(allowed)}")
        return low


class WorkInfoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_info_type: str = Field(default=WorkInfoType.GENERAL.value, max_length=80)
    source: str | None = Field(default=None, max_length=200)
    summary: str = Field(min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=10000)
    locked: bool = False
    view_access: ViewAccess = ViewAccess.INTERNAL
    itsm_ticket_ref: ItsmTicketRef | None = None

    @field_validator("work_info_type", "summary")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("source", "notes")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class WorkInfoUpdate(BaseModel):
    """Partial update — locked entries reject mutations in the service layer."""

    model_config = ConfigDict(extra="forbid")

    work_info_type: str | None = Field(default=None, max_length=80)
    source: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=10000)
    locked: bool | None = None
    view_access: ViewAccess | None = None
    itsm_ticket_ref: ItsmTicketRef | None = None

    @field_validator("work_info_type", "summary")
    @classmethod
    def _strip_required_opt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("source", "notes")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _at_least_one(self) -> WorkInfoUpdate:
        fields = self.model_dump(exclude_unset=True)
        if not fields:
            raise ValueError("at least one field is required")
        return self


def to_work_info_row(doc: dict[str, Any]) -> dict[str, Any]:
    ref = doc.get("itsm_ticket_ref")
    return {
        "work_info_id": doc.get("work_info_id"),
        "tenant_id": doc.get("tenant_id"),
        "component_id": doc.get("component_id"),
        "work_info_type": doc.get("work_info_type"),
        "source": doc.get("source"),
        "summary": doc.get("summary"),
        "notes": doc.get("notes"),
        "locked": bool(doc.get("locked")),
        "view_access": doc.get("view_access") or ViewAccess.INTERNAL.value,
        "attachment_ids": list(doc.get("attachment_ids") or []),
        "attachment_count": len(doc.get("attachment_ids") or []),
        "itsm_ticket_ref": ref if isinstance(ref, dict) else None,
        "created_by": doc.get("created_by"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }
