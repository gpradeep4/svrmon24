"""SLA policy and tracking models (multi-dimensional matching)."""

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

# Well-known service tiers; free-form labels also allowed on match.service_tier.
SLA_SERVICE_TIERS: tuple[str, ...] = ("tier1", "tier2", "tier3")
SLA_CUSTOMER_CLASSES: tuple[str, ...] = ("vip", "premium", "standard")

SlaMetric = Literal["response", "resolution"]
SlaTrackingStatus = Literal["running", "paused", "met", "breached", "cancelled"]
SlaPriority = Literal["p1", "p2", "p3", "p4"]

# Specificity weights for match scoring (most specific wins).
MATCH_WEIGHTS: dict[str, int] = {
    "service_tier": 100,
    "ci_criticality": 90,
    "ci_tier": 85,
    "customer_class": 80,
    "category": 60,
    "subcategory": 50,
    "assignment_group": 40,
    "urgency": 30,
    "impact": 30,
    "priorities": 20,
}


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
    """Calendar settings (24×7 by default; business-hours + holidays drive clock math)."""

    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    business_hours_only: bool = False
    business_hours_start: str | None = Field(
        default=None, max_length=8, description="HH:MM local, e.g. 09:00"
    )
    business_hours_end: str | None = Field(
        default=None, max_length=8, description="HH:MM local, e.g. 17:00"
    )
    business_days: list[str] | None = Field(
        default=None,
        max_length=7,
        description="Optional weekdays: mon..sun; null = Mon–Fri when business_hours_only",
    )
    holidays: list[str] | None = Field(
        default=None,
        max_length=366,
        description="YYYY-MM-DD dates excluded from business-hours clocks",
    )

    @field_validator("holidays", mode="before")
    @classmethod
    def _clean_holidays(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("holidays must be a list of YYYY-MM-DD strings")
        out: list[str] = []
        seen: set[str] = set()
        for raw in value:
            item = str(raw or "").strip()[:10]
            if not item or item in seen:
                continue
            # Soft format check — clock math skips unparsable entries.
            if len(item) != 10 or item[4] != "-" or item[7] != "-":
                raise ValueError(f"Invalid holiday date '{raw}' (expected YYYY-MM-DD)")
            seen.add(item)
            out.append(item)
        return out or None


def _clean_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    item = str(value).strip()
    return item or None


def _clean_str_list(values: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        item = str(raw or "").strip()
        if not item or item.lower() in seen:
            continue
        seen.add(item.lower())
        out.append(item)
    return out


class SlaMatchConditions(BaseModel):
    """Optional match dimensions. Null / empty = wildcard (matches any ticket).

    When a field is set, the ticket must match (case-insensitive) for the policy
    to apply. Specificity score sums weights for each non-wildcard that matches.
    """

    model_config = ConfigDict(extra="forbid")

    service_tier: str | None = Field(
        default=None,
        max_length=64,
        description="e.g. tier1 / tier2 / tier3 or free-form label",
    )
    customer_class: str | None = Field(
        default=None,
        max_length=64,
        description="e.g. vip / premium / standard",
    )
    category: str | None = Field(default=None, max_length=128)
    subcategory: str | None = Field(default=None, max_length=128)
    assignment_group: str | None = Field(default=None, max_length=128)
    urgency: str | None = Field(default=None, max_length=64)
    impact: str | None = Field(default=None, max_length=64)
    ci_criticality: str | None = Field(
        default=None,
        max_length=64,
        description="Match ticket.ci_criticality or any ci_links[].criticality",
    )
    ci_tier: str | None = Field(
        default=None,
        max_length=64,
        description="Match ticket.ci_tier or any ci_links[].ci_tier",
    )
    priorities: list[SlaPriority] | None = Field(
        default=None,
        max_length=4,
        description="If set, ticket priority must be one of these",
    )

    @field_validator(
        "service_tier",
        "customer_class",
        "category",
        "subcategory",
        "assignment_group",
        "urgency",
        "impact",
        "ci_criticality",
        "ci_tier",
        mode="before",
    )
    @classmethod
    def _strip_optional(cls, value: object) -> str | None:
        if value is None:
            return None
        return _clean_optional_str(str(value))

    @field_validator("priorities", mode="before")
    @classmethod
    def _clean_priorities(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("priorities must be a list")
        cleaned = _clean_str_list([str(v) for v in value])
        for item in cleaned:
            if item not in INCIDENT_PRIORITIES:
                raise ValueError(f"Invalid priority '{item}' in match.priorities")
        return cleaned or None


class SlaPolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    active: bool = True
    applies_to: TicketType
    # Lower number = higher precedence when specificity scores tie (default 100).
    priority_order: int = Field(default=100, ge=0, le=10000)
    match: SlaMatchConditions = Field(default_factory=SlaMatchConditions)
    targets: list[SlaTarget] = Field(min_length=1, max_length=8)
    pause_on_statuses: list[str] = Field(default_factory=list, max_length=32)
    calendar: SlaCalendar = Field(default_factory=SlaCalendar)

    @field_validator("pause_on_statuses")
    @classmethod
    def _clean_statuses(cls, value: list[str]) -> list[str]:
        return _clean_str_list(value)

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
    priority_order: int | None = Field(default=None, ge=0, le=10000)
    match: SlaMatchConditions | None = None
    targets: list[SlaTarget] | None = Field(default=None, min_length=1, max_length=8)
    pause_on_statuses: list[str] | None = Field(default=None, max_length=32)
    calendar: SlaCalendar | None = None

    @field_validator("pause_on_statuses")
    @classmethod
    def _clean_statuses(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _clean_str_list(value)

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
    "MATCH_WEIGHTS",
    "SLA_CUSTOMER_CLASSES",
    "SLA_METRICS",
    "SLA_SERVICE_TIERS",
    "SLA_TRACKING_STATUSES",
    "SlaCalendar",
    "SlaMatchConditions",
    "SlaPolicyCreate",
    "SlaPolicyUpdate",
    "SlaPriorityTarget",
    "SlaTarget",
    "SlaTrackingPause",
    "default_priority_minutes",
]
