"""Knowledge article request models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

KNOWLEDGE_STATUSES: tuple[str, ...] = ("draft", "published", "retired")

KnowledgeStatus = Literal["draft", "published", "retired"]

# Allowed status transitions (from → to).
KNOWLEDGE_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"published", "retired"}),
    "published": frozenset({"retired", "draft"}),
    "retired": frozenset({"draft"}),
}


class KnowledgeArticleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=200000)
    status: KnowledgeStatus = "draft"
    category: str | None = Field(default=None, max_length=128)
    tags: list[str] = Field(default_factory=list)
    related_incident_ids: list[str] = Field(default_factory=list)
    related_problem_ids: list[str] = Field(default_factory=list)
    related_component_ids: list[str] = Field(default_factory=list)


class KnowledgeArticleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    body: str | None = Field(default=None, min_length=1, max_length=200000)
    category: str | None = Field(default=None, max_length=128)
    tags: list[str] | None = None
    related_incident_ids: list[str] | None = None
    related_problem_ids: list[str] | None = None
    related_component_ids: list[str] | None = None


class KnowledgeArticleTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: KnowledgeStatus
    comment: str | None = Field(default=None, max_length=4000)
