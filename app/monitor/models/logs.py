"""Monitoring log streams + events — SIMULATED default; LIVE ingest later."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .literals import CollectMode, DataSource, ExecutionMode

# Demo source tag: collect-path labels plus explicit simulated.
LogSource = Literal["agentless", "agent", "simulated"]
LogSeverity = Literal["debug", "info", "warning", "error", "critical"]
StreamStatus = Literal["active", "paused", "error"]
SourceKind = Literal[
    "application",
    "system",
    "security",
    "access",
    "database",
    "network",
    "other",
]


class LogStream(BaseModel):
    """Logical log stream, optionally linked to a CMDB CI."""

    model_config = ConfigDict(extra="ignore")

    stream_id: str
    name: str
    component_id: str | None = None
    target_id: str | None = None
    source_kind: SourceKind = "application"
    status: StreamStatus = "active"
    collect_mode: CollectMode = "AGENTLESS"
    execution_mode: ExecutionMode = "SIMULATED"
    data_source: DataSource = "SYNTHETIC_DEMO"
    tenant_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LogEvent(BaseModel):
    """One searchable log event (SIMULATED or LIVE)."""

    model_config = ConfigDict(extra="ignore")

    event_id: str
    stream_id: str
    component_id: str | None = None
    target_id: str | None = None
    severity: LogSeverity = "info"
    message: str
    attrs: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime
    data_source: DataSource = "SYNTHETIC_DEMO"
    execution_mode: ExecutionMode = "SIMULATED"
    collect_mode: CollectMode | None = None
    source: LogSource = "simulated"
    tenant_id: str | None = None
    created_at: datetime | None = None


class SimulateTickResult(BaseModel):
    """Summary of a demo simulate-tick write."""

    model_config = ConfigDict(extra="ignore")

    tenant_id: str
    streams_ensured: int = 0
    events_created: int = 0
    events_trimmed: int = 0
    retained_total: int = 0
    retention_limit: int | None = None
    ticks_today: int = 0
    ticks_limit: int | None = None
    execution_mode: ExecutionMode = "SIMULATED"
    live_probes: bool = False
