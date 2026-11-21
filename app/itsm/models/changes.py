"""Change request models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import CHANGE_TYPES, ChangeStatus, ChangeType, CiLink, IncidentPriority


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


class ChangeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20000)
    justification: str | None = Field(default=None, max_length=20000)
    status: ChangeStatus = "draft"
    change_type: ChangeType = "normal"
    risk: str | None = Field(default=None, max_length=64)
    impact: str | None = Field(default=None, max_length=64)
    priority: IncidentPriority = "p3"
    category: str | None = Field(default=None, max_length=128)
    subcategory: str | None = Field(default=None, max_length=128)
    urgency: str | None = Field(default=None, max_length=64)
    assignment_group: str | None = Field(default=None, max_length=128)
    assignee_user_id: str | None = Field(default=None, max_length=128)
    service_tier: str | None = Field(default=None, max_length=64)
    customer_class: str | None = Field(default=None, max_length=64)
    ci_tier: str | None = Field(default=None, max_length=64)
    ci_criticality: str | None = Field(default=None, max_length=64)
    planned_start: str | None = Field(default=None, max_length=64)
    planned_end: str | None = Field(default=None, max_length=64)
    implementation_plan: str | None = Field(default=None, max_length=20000)
    test_plan: str | None = Field(default=None, max_length=20000)
    backout_plan: str | None = Field(default=None, max_length=20000)
    cab_required: bool = False
    ci_links: list[CiLink] = Field(default_factory=list)
    related_incident_ids: list[str] = Field(default_factory=list)
    related_problem_ids: list[str] = Field(default_factory=list)
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


class ChangeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20000)
    justification: str | None = Field(default=None, max_length=20000)
    change_type: ChangeType | None = None
    risk: str | None = Field(default=None, max_length=64)
    impact: str | None = Field(default=None, max_length=64)
    priority: IncidentPriority | None = None
    category: str | None = Field(default=None, max_length=128)
    subcategory: str | None = Field(default=None, max_length=128)
    urgency: str | None = Field(default=None, max_length=64)
    assignment_group: str | None = Field(default=None, max_length=128)
    assignee_user_id: str | None = Field(default=None, max_length=128)
    service_tier: str | None = Field(default=None, max_length=64)
    customer_class: str | None = Field(default=None, max_length=64)
    ci_tier: str | None = Field(default=None, max_length=64)
    ci_criticality: str | None = Field(default=None, max_length=64)
    planned_start: str | None = Field(default=None, max_length=64)
    planned_end: str | None = Field(default=None, max_length=64)
    actual_start: str | None = Field(default=None, max_length=64)
    actual_end: str | None = Field(default=None, max_length=64)
    implementation_plan: str | None = Field(default=None, max_length=20000)
    test_plan: str | None = Field(default=None, max_length=20000)
    backout_plan: str | None = Field(default=None, max_length=20000)
    cab_required: bool | None = None
    related_incident_ids: list[str] | None = None
    related_problem_ids: list[str] | None = None
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


class ChangeTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ChangeStatus
    comment: str | None = Field(default=None, max_length=4000)


class ChangeCiLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(min_length=1, max_length=128)


# Re-export for callers that want the tuple.
__all__ = [
    "CHANGE_TYPES",
    "ChangeCreate",
    "ChangeUpdate",
    "ChangeTransition",
    "ChangeCiLinkCreate",
]
