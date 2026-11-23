"""Service Portal request models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .catalog import COLLECT_MODES, TARGET_PLACEMENTS

REQUEST_STATUSES: tuple[str, ...] = (
    "draft",
    "submitted",
    "pending_approval",
    "approved",
    "rejected",
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
)

EXECUTION_MODES: tuple[str, ...] = ("SIMULATED", "LIVE", "DRY_RUN")

RequestStatus = Literal[
    "draft",
    "submitted",
    "pending_approval",
    "approved",
    "rejected",
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
]
CollectMode = Literal["agentless", "agent"]
TargetPlacement = Literal["on_prem", "cloud", "either"]
ExecutionMode = Literal["SIMULATED", "LIVE", "DRY_RUN"]

CANCELABLE_STATUSES = frozenset({"draft", "submitted", "pending_approval"})


class RequestCreate(BaseModel):
    """Create a draft request (or submit immediately when ``submit`` is true)."""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=64)
    form_values: dict[str, Any] = Field(default_factory=dict)
    collect_mode: CollectMode | None = None
    target_placement: TargetPlacement | None = None
    component_id: str | None = Field(default=None, max_length=128)
    linked_incident_id: str | None = Field(default=None, max_length=64)
    requested_execution_mode: ExecutionMode = "SIMULATED"
    priority: str | None = Field(default=None, max_length=16)
    submit: bool = False

    @field_validator("item_id", "component_id", "linked_incident_id", mode="before")
    @classmethod
    def _strip_optional(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("collect_mode")
    @classmethod
    def _collect_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in COLLECT_MODES:
            raise ValueError(f"collect_mode must be one of {COLLECT_MODES}")
        return value

    @field_validator("target_placement")
    @classmethod
    def _placement_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in TARGET_PLACEMENTS:
            raise ValueError(f"target_placement must be one of {TARGET_PLACEMENTS}")
        return value

    @field_validator("requested_execution_mode")
    @classmethod
    def _exec_ok(cls, value: str) -> str:
        if value not in EXECUTION_MODES:
            raise ValueError(f"requested_execution_mode must be one of {EXECUTION_MODES}")
        return value


class RequestUpdate(BaseModel):
    """Patch a draft request before submit."""

    model_config = ConfigDict(extra="forbid")

    form_values: dict[str, Any] | None = None
    collect_mode: CollectMode | None = None
    target_placement: TargetPlacement | None = None
    component_id: str | None = Field(default=None, max_length=128)
    linked_incident_id: str | None = Field(default=None, max_length=64)
    requested_execution_mode: ExecutionMode | None = None
    priority: str | None = Field(default=None, max_length=16)

    @field_validator("collect_mode")
    @classmethod
    def _collect_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in COLLECT_MODES:
            raise ValueError(f"collect_mode must be one of {COLLECT_MODES}")
        return value

    @field_validator("target_placement")
    @classmethod
    def _placement_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in TARGET_PLACEMENTS:
            raise ValueError(f"target_placement must be one of {TARGET_PLACEMENTS}")
        return value

    @field_validator("requested_execution_mode")
    @classmethod
    def _exec_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in EXECUTION_MODES:
            raise ValueError(f"requested_execution_mode must be one of {EXECUTION_MODES}")
        return value


__all__ = [
    "REQUEST_STATUSES",
    "EXECUTION_MODES",
    "CANCELABLE_STATUSES",
    "RequestCreate",
    "RequestUpdate",
]
