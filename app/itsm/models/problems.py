"""Problem request models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .common import CiLink, ProblemPriority, ProblemStatus


class ProblemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20000)
    status: ProblemStatus = "new"
    priority: ProblemPriority = "p3"
    category: str | None = Field(default=None, max_length=128)
    subcategory: str | None = Field(default=None, max_length=128)
    urgency: str | None = Field(default=None, max_length=64)
    impact: str | None = Field(default=None, max_length=64)
    assignment_group: str | None = Field(default=None, max_length=128)
    assignee_user_id: str | None = Field(default=None, max_length=128)
    service_tier: str | None = Field(default=None, max_length=64)
    customer_class: str | None = Field(default=None, max_length=64)
    ci_tier: str | None = Field(default=None, max_length=64)
    ci_criticality: str | None = Field(default=None, max_length=64)
    root_cause: str | None = Field(default=None, max_length=20000)
    workaround: str | None = Field(default=None, max_length=20000)
    known_error: bool = False
    ci_links: list[CiLink] = Field(default_factory=list)
    related_incident_ids: list[str] = Field(default_factory=list)
    change_id: str | None = Field(default=None, max_length=128)


class ProblemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=20000)
    priority: ProblemPriority | None = None
    category: str | None = Field(default=None, max_length=128)
    subcategory: str | None = Field(default=None, max_length=128)
    urgency: str | None = Field(default=None, max_length=64)
    impact: str | None = Field(default=None, max_length=64)
    assignment_group: str | None = Field(default=None, max_length=128)
    assignee_user_id: str | None = Field(default=None, max_length=128)
    service_tier: str | None = Field(default=None, max_length=64)
    customer_class: str | None = Field(default=None, max_length=64)
    ci_tier: str | None = Field(default=None, max_length=64)
    ci_criticality: str | None = Field(default=None, max_length=64)
    root_cause: str | None = Field(default=None, max_length=20000)
    workaround: str | None = Field(default=None, max_length=20000)
    known_error: bool | None = None
    related_incident_ids: list[str] | None = None
    change_id: str | None = Field(default=None, max_length=128)


class ProblemTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ProblemStatus
    root_cause: str | None = Field(default=None, max_length=20000)
    workaround: str | None = Field(default=None, max_length=20000)
    comment: str | None = Field(default=None, max_length=4000)


class ProblemCiLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(min_length=1, max_length=128)
