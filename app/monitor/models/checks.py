"""Agentless monitor checks + results — LIVE path (L1 HTTP/TCP)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .literals import CollectMode, DataSource, ExecutionMode

CheckProtocol = Literal["http", "tcp", "icmp", "snmp"]
# L1 implements http + tcp only; icmp/snmp land in L2.
L1_PROTOCOLS: tuple[str, ...] = ("http", "tcp")


class CheckEndpoint(BaseModel):
    """Probe destination — no secrets. Host/URL required depending on protocol."""

    model_config = ConfigDict(extra="ignore")

    url: str | None = None
    host: str | None = None
    port: int | None = None
    method: str | None = "GET"
    expect_status: int | None = 200
    path: str | None = None


class MonitorCheck(BaseModel):
    """Tenant-scoped agentless check definition."""

    model_config = ConfigDict(extra="ignore")

    check_id: str
    target_id: str
    component_id: str | None = None
    collect_mode: CollectMode = "AGENTLESS"
    protocol: CheckProtocol
    endpoint: CheckEndpoint = Field(default_factory=CheckEndpoint)
    secret_ref: str | None = None
    interval_seconds: int = 60
    timeout_seconds: int = 5
    enabled: bool = True
    # Optional further restriction on top of platform MONITOR_EGRESS_ALLOWLIST.
    egress_allowlist: list[str] = Field(default_factory=list)
    last_run_at: datetime | None = None
    last_result: dict[str, Any] | None = None
    tenant_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MonitorCheckCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target_id: str
    component_id: str | None = None
    protocol: CheckProtocol
    endpoint: CheckEndpoint = Field(default_factory=CheckEndpoint)
    secret_ref: str | None = None
    interval_seconds: int = 60
    timeout_seconds: int = 5
    enabled: bool = True
    egress_allowlist: list[str] = Field(default_factory=list)


class MonitorCheckPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target_id: str | None = None
    component_id: str | None = None
    protocol: CheckProtocol | None = None
    endpoint: CheckEndpoint | None = None
    secret_ref: str | None = None
    interval_seconds: int | None = None
    timeout_seconds: int | None = None
    enabled: bool | None = None
    egress_allowlist: list[str] | None = None


class MonitorCheckResult(BaseModel):
    """Short-retained LIVE check result row."""

    model_config = ConfigDict(extra="ignore")

    result_id: str
    check_id: str
    ok: bool
    latency_ms: float | None = None
    value: float | None = None
    message: str | None = None
    observed_at: datetime
    execution_mode: ExecutionMode = "LIVE"
    data_source: DataSource | None = None
    protocol: CheckProtocol | None = None
    tenant_id: str | None = None
    created_at: datetime | None = None
