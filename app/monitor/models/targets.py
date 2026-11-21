"""Monitoring targets + metric sample models — SIMULATED mode only."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ExecutionMode = Literal["SIMULATED"]
DataSource = Literal["SYNTHETIC_DEMO"]
CollectMode = Literal["AGENTLESS", "AGENT"]
Domain = Literal["server", "network", "application", "database"]
TargetStatus = Literal["unknown", "healthy", "degraded", "down", "maintenance"]
OsFamily = Literal["linux", "windows", "macos", "unix"]
NetworkTargetKind = Literal[
    "switch",
    "router",
    "firewall",
    "load_balancer",
    "access_point",
    "other_network",
]


class MonitorTarget(BaseModel):
    """One monitored CI row (synced from CMDB; not a second inventory)."""

    model_config = ConfigDict(extra="ignore")

    target_id: str
    component_id: str
    component_type: str | None = None
    name_snapshot: str | None = None
    domain: Domain
    target_kind: str | None = None
    os_family: OsFamily | None = None
    os_name: str | None = None
    os_version: str | None = None
    collect_mode: CollectMode = "AGENTLESS"
    status: TargetStatus = "unknown"
    last_sample_at: datetime | None = None
    execution_mode: ExecutionMode = "SIMULATED"
    data_source: DataSource = "SYNTHETIC_DEMO"
    tenant_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MetricSample(BaseModel):
    """Time-series lite sample (SIMULATED / SYNTHETIC_DEMO)."""

    model_config = ConfigDict(extra="ignore")

    sample_id: str
    target_id: str
    component_id: str
    metric_name: str
    value: float
    unit: str | None = None
    observed_at: datetime
    data_source: DataSource = "SYNTHETIC_DEMO"
    collect_mode: CollectMode | None = None
    execution_mode: ExecutionMode = "SIMULATED"
    tenant_id: str | None = None
    created_at: datetime | None = None


class SyncFromCmdbResult(BaseModel):
    """Summary of a CMDB → monitor_targets sync."""

    model_config = ConfigDict(extra="ignore")

    tenant_id: str
    scanned: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    samples_seeded: int = 0
    samples_trimmed: int = 0
    entitlement_limit: int | None = None
    entitlement_truncated: bool = False
    domains: dict[str, int] = Field(default_factory=dict)
    collect_modes: dict[str, int] = Field(default_factory=dict)
