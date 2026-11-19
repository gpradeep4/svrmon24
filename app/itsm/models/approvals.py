"""Approval request models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import TicketType

APPROVAL_STATUSES: tuple[str, ...] = (
    "pending",
    "approved",
    "rejected",
    "cancelled",
)

APPROVAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"approved", "rejected", "cancelled"}),
    "approved": frozenset(),
    "rejected": frozenset(),
    "cancelled": frozenset(),
}

ApprovalStatus = Literal["pending", "approved", "rejected", "cancelled"]
ApprovalDecision = Literal["approved", "rejected"]


class ApprovalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    ticket_type: TicketType
    ticket_id: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=8000)
    approver_user_ids: list[str] = Field(default_factory=list)
    approver_group: str | None = Field(default=None, max_length=128)
    policy: str | None = Field(default=None, max_length=128)
    workflow_execution_id: str | None = Field(default=None, max_length=128)
    node_id: str | None = Field(default=None, max_length=128)


class ApprovalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=8000)
    approver_user_ids: list[str] | None = None
    approver_group: str | None = Field(default=None, max_length=128)
    policy: str | None = Field(default=None, max_length=128)


class ApprovalDecide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ApprovalDecision
    comment: str | None = Field(default=None, max_length=4000)


__all__ = [
    "APPROVAL_STATUSES",
    "APPROVAL_TRANSITIONS",
    "ApprovalCreate",
    "ApprovalUpdate",
    "ApprovalDecide",
]
