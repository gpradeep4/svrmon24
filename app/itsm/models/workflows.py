"""Workflow definition and execution models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

WORKFLOW_APPLIES_TO: tuple[str, ...] = ("incident", "change", "problem", "generic")
WORKFLOW_TRIGGERS: tuple[str, ...] = ("on_create", "on_status", "manual", "schedule")
WORKFLOW_NODE_TYPES: tuple[str, ...] = ("start", "status_change", "approval", "end")
EXECUTION_STATUSES: tuple[str, ...] = (
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
)

WorkflowAppliesTo = Literal["incident", "change", "problem", "generic"]
WorkflowTrigger = Literal["on_create", "on_status", "manual", "schedule"]
WorkflowNodeType = Literal["start", "status_change", "approval", "end"]
ExecutionStatus = Literal[
    "running", "waiting_approval", "completed", "failed", "cancelled"
]
TicketTypeForExec = Literal["incident", "change", "problem"]


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    type: WorkflowNodeType
    label: str | None = Field(default=None, max_length=200)
    # status_change: {"status": "..."}; approval: {"title": "...", "approver_user_ids": [], "approver_group": "..."}
    config: dict[str, Any] = Field(default_factory=dict)
    x: float | None = None
    y: float | None = None


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str | None = Field(default=None, max_length=64)
    from_node: str = Field(alias="from", min_length=1, max_length=64)
    to_node: str = Field(alias="to", min_length=1, max_length=64)
    # Optional branch key: "approved" | "rejected" | None (default)
    condition: str | None = Field(default=None, max_length=64)


class WorkflowGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)


class WorkflowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    applies_to: WorkflowAppliesTo = "generic"
    trigger: WorkflowTrigger = "manual"
    # on_status: {"statuses":["submitted"]}; schedule: {"interval_minutes": 60}
    trigger_config: dict[str, Any] | None = None
    active: bool = False
    graph: WorkflowGraph = Field(default_factory=WorkflowGraph)
    variables_schema: dict[str, Any] | None = None


class WorkflowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    applies_to: WorkflowAppliesTo | None = None
    trigger: WorkflowTrigger | None = None
    trigger_config: dict[str, Any] | None = None
    graph: WorkflowGraph | None = None
    variables_schema: dict[str, Any] | None = None


class WorkflowActivate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool = True


class WorkflowStartExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_type: TicketTypeForExec
    ticket_id: str = Field(min_length=1, max_length=128)
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticket_id")
    @classmethod
    def _strip_ticket_id(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("ticket_id is required")
        return cleaned


class WorkflowAdvance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Optional branch hint when resuming after approval (normally inferred).
    branch: str | None = Field(default=None, max_length=64)
    comment: str | None = Field(default=None, max_length=4000)


__all__ = [
    "WORKFLOW_APPLIES_TO",
    "WORKFLOW_TRIGGERS",
    "WORKFLOW_NODE_TYPES",
    "EXECUTION_STATUSES",
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowGraph",
    "WorkflowCreate",
    "WorkflowUpdate",
    "WorkflowActivate",
    "WorkflowStartExecution",
    "WorkflowAdvance",
]
