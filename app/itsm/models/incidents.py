"""Incident request models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import CiLink, IncidentPriority, IncidentStatus


def _clean_str_list(values: list[str] | None, *, limit: int = 50) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        item = str(raw or "").strip()
        if not item or item.lower() in seen:
            continue
        seen.add(item.lower())
        out.append(item[:320])
        if len(out) >= limit:
            break
    return out


class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20000)
    status: IncidentStatus = "new"
    priority: IncidentPriority = "p3"
    urgency: str | None = Field(default=None, max_length=64)
    impact: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=128)
    subcategory: str | None = Field(default=None, max_length=128)
    assignment_group: str | None = Field(default=None, max_length=128)
    assignee_user_id: str | None = Field(default=None, max_length=128)
    caller_user_id: str | None = Field(default=None, max_length=128)
    caller_email: str | None = Field(default=None, max_length=320)
    service_tier: str | None = Field(
        default=None, max_length=64, description="e.g. tier1 / tier2 / tier3"
    )
    customer_class: str | None = Field(
        default=None, max_length=64, description="e.g. vip / premium / standard"
    )
    ci_tier: str | None = Field(default=None, max_length=64)
    ci_criticality: str | None = Field(default=None, max_length=64)
    ci_links: list[CiLink] = Field(default_factory=list)
    resolution_notes: str | None = Field(default=None, max_length=20000)
    problem_id: str | None = Field(default=None, max_length=128)
    change_id: str | None = Field(default=None, max_length=128)
    watcher_user_ids: list[str] = Field(default_factory=list, max_length=50)
    cc_emails: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("watcher_user_ids", "cc_emails", mode="before")
    @classmethod
    def _clean_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("expected a list")
        return _clean_str_list([str(v) for v in value])


class IncidentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20000)
    priority: IncidentPriority | None = None
    urgency: str | None = Field(default=None, max_length=64)
    impact: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=128)
    subcategory: str | None = Field(default=None, max_length=128)
    assignment_group: str | None = Field(default=None, max_length=128)
    assignee_user_id: str | None = Field(default=None, max_length=128)
    caller_user_id: str | None = Field(default=None, max_length=128)
    caller_email: str | None = Field(default=None, max_length=320)
    service_tier: str | None = Field(default=None, max_length=64)
    customer_class: str | None = Field(default=None, max_length=64)
    ci_tier: str | None = Field(default=None, max_length=64)
    ci_criticality: str | None = Field(default=None, max_length=64)
    resolution_notes: str | None = Field(default=None, max_length=20000)
    problem_id: str | None = Field(default=None, max_length=128)
    change_id: str | None = Field(default=None, max_length=128)
    watcher_user_ids: list[str] | None = Field(default=None, max_length=50)
    cc_emails: list[str] | None = Field(default=None, max_length=50)

    @field_validator("watcher_user_ids", "cc_emails", mode="before")
    @classmethod
    def _clean_lists(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("expected a list")
        return _clean_str_list([str(v) for v in value])


class IncidentTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: IncidentStatus
    resolution_notes: str | None = Field(default=None, max_length=20000)
    comment: str | None = Field(default=None, max_length=4000)


class IncidentCiLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(min_length=1, max_length=128)
