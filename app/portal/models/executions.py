"""Service Portal execution run models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RUN_STATUSES: tuple[str, ...] = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
)

RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
CollectMode = Literal["agentless", "agent"]
ExecutionMode = Literal["SIMULATED", "LIVE", "DRY_RUN"]


class ExecutionRequeue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False
    collect_mode: CollectMode | None = None


class SimulateTickBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=100)


__all__ = [
    "RUN_STATUSES",
    "ExecutionRequeue",
    "SimulateTickBody",
]
