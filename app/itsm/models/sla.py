"""SLA policy and tracking models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import INCIDENT_PRIORITIES, TicketType

SLA_METRICS: tuple[str, ...] = ("response", "resolution")
SLA_TRACKING_STATUSES: tuple[str, ...] = (
    "running",
    "paused",
    "met",
    "breached",
    "cancelled",
)

SlaMetric = Literal["response", "resolution"]
SlaTrackingStatus = Literal["running", "paused", "met", "breached", "cancelled"]
SlaPriority = Literal["p1", "p2", "p3", "p4"]


class SlaPriorityTarget(BaseModel):
    """Minutes allowed for a single priority."""

    model_config = ConfigDict(extra="forbid")

    priority: SlaPriority
    minutes: int = Field(ge=1, le=525600)


class SlaTarget(BaseModel):
    """One SLA metric with priority → minutes mappings."""

    model_config = ConfigDict(extra="forbid")

    metric: SlaMetric
    priority_targets: list[SlaPriorityTarget] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _unique_priorities(self) -> SlaTarget:
        seen: set[str] = set()
        for row in self.priority_targets:
            if row.priority in seen:
                raise ValueError(f"Duplicate priority '{row.priority}' in target")
            seen.add(row.priority)
        return self


class SlaCalendar(BaseModel):
    """Basic calendar settings (24×7 by default; business-hours flag only)."""

    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    business_hours_only: bool = False


class SlaPolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    active: bool = True
    applies_to: TicketType
    targets: list[SlaTarget] = Field(min_length=1, max_length=8)
    pause_on_statuses: list[str] = Field(default_factory=list, max_length=32)
    calendar: SlaCalendar = Field(default_factory=SlaCalendar)

    @field_validator("pause_on_statuses")
    @classmethod
    def _clean_statuses(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in value or []:
            item = str(raw or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    @model_validator(mode="after")
    def _unique_metrics(self) -> SlaPolicyCreate:
        metrics = [t.metric for t in self.targets]
        if len(metrics) != len(set(metrics)):
            raise ValueError("Duplicate metric in targets")
        return self


class SlaPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    active: bool | None = None
    targets: list[SlaTarget] | None = Field(default=None, min_length=1, max_length=8)
    pause_on_statuses: list[str] | None = Field(default=None, max_length=32)
    calendar: SlaCalendar | None = None

    @field_validator("pause_on_statuses")
    @classmethod
    def _clean_statuses(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        out: list[str] = []
        seen: set[str] = set()
        for raw in value:
            item = str(raw or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    @model_validator(mode="after")
    def _unique_metrics(self) -> SlaPolicyUpdate:
        if self.targets is None:
            return self
        metrics = [t.metric for t in self.targets]
        if len(metrics) != len(set(metrics)):
            raise ValueError("Duplicate metric in targets")
        return self


class SlaTrackingPause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paused: bool = True
    comment: str | None = Field(default=None, max_length=2000)


def default_priority_minutes(priority: str) -> int | None:
    """Fallback minutes when a policy target omits a priority (should not normally apply)."""
    table = {"p1": 15, "p2": 60, "p3": 240, "p4": 1440}
    if priority not in INCIDENT_PRIORITIES:
        return None
    return table.get(priority)


__all__ = [
    "SLA_METRICS",
    "SLA_TRACKING_STATUSES",
    "SlaCalendar",
    "SlaPolicyCreate",
    "SlaPolicyUpdate",
    "SlaPriorityTarget",
    "SlaTarget",
    "SlaTrackingPause",
    "default_priority_minutes",
]
