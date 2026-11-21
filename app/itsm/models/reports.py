"""Custom ITSM report definition request models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import (
    CHANGE_STATUSES,
    INCIDENT_PRIORITIES,
    INCIDENT_STATUSES,
    PROBLEM_STATUSES,
    TICKET_TYPES,
)

ReportMetric = Literal[
    "open_incidents",
    "open_changes",
    "open_problems",
    "pending_approvals",
    "sla_breaches",
    "sla_at_risk",
    "workflows_in_progress",
    "knowledge_published",
    "notifications_unread",
    "created_incidents",
    "created_changes",
    "created_problems",
    "resolved_incidents",
    "resolved_changes",
    "resolved_problems",
    "ticket_rows",
]

REPORT_METRICS: tuple[str, ...] = (
    "open_incidents",
    "open_changes",
    "open_problems",
    "pending_approvals",
    "sla_breaches",
    "sla_at_risk",
    "workflows_in_progress",
    "knowledge_published",
    "notifications_unread",
    "created_incidents",
    "created_changes",
    "created_problems",
    "resolved_incidents",
    "resolved_changes",
    "resolved_problems",
    "ticket_rows",
)

DEFAULT_TICKET_COLUMNS: tuple[str, ...] = (
    "ticket_type",
    "ticket_id",
    "number",
    "title",
    "status",
    "priority",
    "category",
    "service_tier",
    "assignee_user_id",
    "created_at",
    "updated_at",
)

ALLOWED_TICKET_COLUMNS: frozenset[str] = frozenset(DEFAULT_TICKET_COLUMNS)

ALL_TICKET_STATUSES: frozenset[str] = frozenset(
    {*INCIDENT_STATUSES, *CHANGE_STATUSES, *PROBLEM_STATUSES}
)
ALL_PRIORITIES: frozenset[str] = frozenset(INCIDENT_PRIORITIES)


class ReportFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_types: list[str] = Field(default_factory=lambda: list(TICKET_TYPES))
    statuses: list[str] = Field(default_factory=list)
    priorities: list[str] = Field(default_factory=list)
    category: str | None = Field(default=None, max_length=128)
    service_tier: str | None = Field(default=None, max_length=64)
    window_days: int | None = Field(default=30, description="7 or 30; null = no window")
    date_from: str | None = Field(
        default=None, max_length=32, description="Optional ISO date (YYYY-MM-DD)"
    )
    date_to: str | None = Field(
        default=None, max_length=32, description="Optional ISO date (YYYY-MM-DD)"
    )

    @field_validator("ticket_types")
    @classmethod
    def _validate_ticket_types(cls, value: list[str]) -> list[str]:
        if not value:
            return list(TICKET_TYPES)
        out: list[str] = []
        seen: set[str] = set()
        for raw in value:
            item = str(raw or "").strip().lower()
            if item not in TICKET_TYPES:
                raise ValueError(f"Invalid ticket_type '{raw}'")
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out or list(TICKET_TYPES)

    @field_validator("statuses")
    @classmethod
    def _validate_statuses(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in value or []:
            item = str(raw or "").strip().lower()
            if not item:
                continue
            if item not in ALL_TICKET_STATUSES:
                raise ValueError(f"Invalid status '{raw}'")
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    @field_validator("priorities")
    @classmethod
    def _validate_priorities(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in value or []:
            item = str(raw or "").strip().lower()
            if not item:
                continue
            if item not in ALL_PRIORITIES:
                raise ValueError(f"Invalid priority '{raw}'")
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    @field_validator("window_days")
    @classmethod
    def _validate_window(cls, value: int | None) -> int | None:
        if value is None:
            return None
        days = int(value)
        if days not in (7, 30):
            raise ValueError("window_days must be 7, 30, or null")
        return days

    @field_validator("category", "service_tier")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @model_validator(mode="after")
    def _date_range(self) -> ReportFilters:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class ReportDefinitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    metrics: list[ReportMetric] = Field(min_length=1)
    filters: ReportFilters = Field(default_factory=ReportFilters)
    columns: list[str] = Field(default_factory=lambda: list(DEFAULT_TICKET_COLUMNS))

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("name is required")
        return cleaned

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator("metrics")
    @classmethod
    def _dedupe_metrics(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in value:
            item = str(raw)
            if item not in REPORT_METRICS:
                raise ValueError(f"Invalid metric '{raw}'")
            if item not in seen:
                seen.add(item)
                out.append(item)
        if not out:
            raise ValueError("metrics must include at least one value")
        return out

    @field_validator("columns")
    @classmethod
    def _validate_columns(cls, value: list[str]) -> list[str]:
        if not value:
            return list(DEFAULT_TICKET_COLUMNS)
        out: list[str] = []
        seen: set[str] = set()
        for raw in value:
            item = str(raw or "").strip()
            if item not in ALLOWED_TICKET_COLUMNS:
                raise ValueError(f"Invalid column '{raw}'")
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out or list(DEFAULT_TICKET_COLUMNS)


class ReportDefinitionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    metrics: list[ReportMetric] | None = None
    filters: ReportFilters | None = None
    columns: list[str] | None = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("name cannot be empty")
        return cleaned

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator("metrics")
    @classmethod
    def _dedupe_metrics(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        out: list[str] = []
        seen: set[str] = set()
        for raw in value:
            item = str(raw)
            if item not in REPORT_METRICS:
                raise ValueError(f"Invalid metric '{raw}'")
            if item not in seen:
                seen.add(item)
                out.append(item)
        if not out:
            raise ValueError("metrics must include at least one value")
        return out

    @field_validator("columns")
    @classmethod
    def _validate_columns(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not value:
            return list(DEFAULT_TICKET_COLUMNS)
        out: list[str] = []
        seen: set[str] = set()
        for raw in value:
            item = str(raw or "").strip()
            if item not in ALLOWED_TICKET_COLUMNS:
                raise ValueError(f"Invalid column '{raw}'")
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out or list(DEFAULT_TICKET_COLUMNS)


ReportExportFormat = Literal["csv", "xlsx"]
ReportScheduleChannel = Literal["email"]


class ReportScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=200)
    interval_minutes: int = Field(default=1440, ge=5, le=10080)
    timezone: str = Field(default="UTC", max_length=64)
    recipients: list[str] = Field(min_length=1, max_length=50)
    channels: list[ReportScheduleChannel] = Field(default_factory=lambda: ["email"])
    format: ReportExportFormat = "csv"
    active: bool = True

    @field_validator("report_id")
    @classmethod
    def _clean_report_id(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("report_id is required")
        return cleaned

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator("timezone")
    @classmethod
    def _timezone_default(cls, value: str | None) -> str:
        cleaned = (value or "UTC").strip() or "UTC"
        return cleaned[:64]

    @field_validator("recipients")
    @classmethod
    def _clean_recipients(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in value or []:
            item = str(raw or "").strip().lower()
            if not item or "@" not in item:
                raise ValueError(f"Invalid recipient email '{raw}'")
            if item not in seen:
                seen.add(item)
                out.append(item)
            if len(out) >= 50:
                break
        if not out:
            raise ValueError("recipients must include at least one email")
        return out

    @field_validator("channels")
    @classmethod
    def _clean_channels(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for raw in value or ["email"]:
            item = str(raw or "").strip().lower()
            if item != "email":
                raise ValueError("Only email channel is supported for schedules in N3")
            if item not in out:
                out.append(item)
        return out or ["email"]


class ReportScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    timezone: str | None = Field(default=None, max_length=64)
    recipients: list[str] | None = Field(default=None, max_length=50)
    channels: list[ReportScheduleChannel] | None = None
    format: ReportExportFormat | None = None
    active: bool | None = None

    @field_validator("name", "timezone")
    @classmethod
    def _strip_optional_str(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator("recipients")
    @classmethod
    def _clean_recipients(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        out: list[str] = []
        seen: set[str] = set()
        for raw in value or []:
            item = str(raw or "").strip().lower()
            if not item or "@" not in item:
                raise ValueError(f"Invalid recipient email '{raw}'")
            if item not in seen:
                seen.add(item)
                out.append(item)
            if len(out) >= 50:
                break
        if not out:
            raise ValueError("recipients must include at least one email")
        return out

    @field_validator("channels")
    @classmethod
    def _clean_channels(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        out: list[str] = []
        for raw in value or ["email"]:
            item = str(raw or "").strip().lower()
            if item != "email":
                raise ValueError("Only email channel is supported for schedules in N3")
            if item not in out:
                out.append(item)
        return out or ["email"]
