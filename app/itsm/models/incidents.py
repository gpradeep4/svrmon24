"""Incident request models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .common import CiLink, IncidentPriority, IncidentStatus


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
    ci_links: list[CiLink] = Field(default_factory=list)
    resolution_notes: str | None = Field(default=None, max_length=20000)
    problem_id: str | None = Field(default=None, max_length=128)
    change_id: str | None = Field(default=None, max_length=128)


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
    resolution_notes: str | None = Field(default=None, max_length=20000)
    problem_id: str | None = Field(default=None, max_length=128)
    change_id: str | None = Field(default=None, max_length=128)


class IncidentTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: IncidentStatus
    resolution_notes: str | None = Field(default=None, max_length=20000)
    comment: str | None = Field(default=None, max_length=4000)


class IncidentCiLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(min_length=1, max_length=128)
