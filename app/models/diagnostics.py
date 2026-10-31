"""Diagnostic request/response models — SIMULATED mode only."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ExecutionMode = Literal["SIMULATED"]

# Keys that must never appear on diagnostic start requests (no remote exec path).
FORBIDDEN_EXECUTION_KEYS = frozenset(
    {
        "command",
        "commands",
        "cmd",
        "script",
        "scripts",
        "shell",
        "bash",
        "powershell",
        "sql",
        "query",
        "ssh",
        "winrm",
        "payload",
        "argv",
        "executable",
        "remote_command",
        "scan",
        "probe",
        "live",
        "execution_mode",  # clients cannot override; always SIMULATED
    }
)


class DiagnosticStartRequest(BaseModel):
    """Start a simulated diagnostic. Extra/forbidden execution fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(min_length=1, max_length=128)
    profile_name: str = Field(min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("component_id", "profile_name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be blank")
        return cleaned

    @field_validator("notes")
    @classmethod
    def strip_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="before")
    @classmethod
    def reject_execution_payloads(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        lowered = {str(key).lower() for key in data}
        banned = lowered & FORBIDDEN_EXECUTION_KEYS
        if banned:
            raise ValueError(
                "Diagnostic requests cannot include execution payloads "
                f"({', '.join(sorted(banned))}). "
                "Only approved simulated profiles are allowed."
            )
        return data


class DiagnosticCheckResult(BaseModel):
    check_id: str
    label: str
    metric_kind: str
    unit: str
    value: Any
    status: str
    synthetic: bool = True
    data_source: Literal["SYNTHETIC_DEMO"] = "SYNTHETIC_DEMO"
    note: str = "Synthetic demo value — not real telemetry."


class DiagnosticRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    diagnostic_id: str
    timestamp: datetime
    execution_mode: ExecutionMode = "SIMULATED"
    profile_name: str
    component_id: str
    component: dict[str, Any]
    dependency_context: dict[str, Any]
    checks: list[dict[str, Any]]
    summary: dict[str, Any]
    labels: dict[str, Any]
    notes: str | None = None
    created_at: datetime
