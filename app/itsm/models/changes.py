"""Change request models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .common import CHANGE_TYPES, ChangeStatus, ChangeType, CiLink, IncidentPriority


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
    assignment_group: str | None = Field(default=None, max_length=128)
    assignee_user_id: str | None = Field(default=None, max_length=128)
    planned_start: str | None = Field(default=None, max_length=64)
    planned_end: str | None = Field(default=None, max_length=64)
    implementation_plan: str | None = Field(default=None, max_length=20000)
    test_plan: str | None = Field(default=None, max_length=20000)
    backout_plan: str | None = Field(default=None, max_length=20000)
    cab_required: bool = False
    ci_links: list[CiLink] = Field(default_factory=list)
    related_incident_ids: list[str] = Field(default_factory=list)
    related_problem_ids: list[str] = Field(default_factory=list)


class ChangeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20000)
    justification: str | None = Field(default=None, max_length=20000)
    change_type: ChangeType | None = None
    risk: str | None = Field(default=None, max_length=64)
    impact: str | None = Field(default=None, max_length=64)
    priority: IncidentPriority | None = None
    assignment_group: str | None = Field(default=None, max_length=128)
    assignee_user_id: str | None = Field(default=None, max_length=128)
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
