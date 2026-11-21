"""Monitoring alert rules + instances — SIMULATED evaluation only."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ExecutionMode = Literal["SIMULATED"]
DataSource = Literal["SYNTHETIC_DEMO"]
AlertSeverity = Literal["info", "warning", "error", "critical"]
AlertStatus = Literal["firing", "acked", "resolved"]
ConditionType = Literal["threshold", "log_match", "file_change"]
ThresholdOperator = Literal["gt", "gte", "lt", "lte", "eq"]


class AlertScope(BaseModel):
    """Optional narrowing for a rule (domain / CI / stream / target)."""

    model_config = ConfigDict(extra="ignore")

    domain: str | None = None
    component_id: str | None = None
    target_id: str | None = None
    stream_id: str | None = None
    watch_id: str | None = None


class AlertCondition(BaseModel):
    """SIMULATED condition evaluated against synthetic metrics/logs/file events."""

    model_config = ConfigDict(extra="ignore")

    type: ConditionType
    # threshold
    metric_name: str | None = None
    operator: ThresholdOperator | None = None
    value: float | None = None
    # log_match
    severity: str | None = None  # single or comma-separated
    message_contains: str | None = None
    # file_change
    path_contains: str | None = None


class AlertRule(BaseModel):
    """Tenant-scoped alert rule definition."""

    model_config = ConfigDict(extra="ignore")

    rule_id: str
    name: str
    enabled: bool = True
    scope: AlertScope = Field(default_factory=AlertScope)
    condition: AlertCondition
    severity: AlertSeverity = "warning"
    description: str | None = None
    execution_mode: ExecutionMode = "SIMULATED"
    data_source: DataSource = "SYNTHETIC_DEMO"
    tenant_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AlertRuleCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    enabled: bool = True
    scope: AlertScope = Field(default_factory=AlertScope)
    condition: AlertCondition
    severity: AlertSeverity = "warning"
    description: str | None = None


class AlertRulePatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    enabled: bool | None = None
    scope: AlertScope | None = None
    condition: AlertCondition | None = None
    severity: AlertSeverity | None = None
    description: str | None = None


class AlertInstance(BaseModel):
    """Firing / acked / resolved alert lifecycle (Monitoring only — no ITSM write)."""

    model_config = ConfigDict(extra="ignore")

    alert_id: str
    rule_id: str
    rule_name: str | None = None
    component_id: str | None = None
    target_id: str | None = None
    stream_id: str | None = None
    watch_id: str | None = None
    fingerprint: str
    status: AlertStatus = "firing"
    severity: AlertSeverity = "warning"
    summary: str
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    suggested_incident_id: str | None = None
    fired_at: datetime
    acked_at: datetime | None = None
    resolved_at: datetime | None = None
    acked_by: str | None = None
    resolved_by: str | None = None
    execution_mode: ExecutionMode = "SIMULATED"
    data_source: DataSource = "SYNTHETIC_DEMO"
    tenant_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EvaluateAlertsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str
    rules_evaluated: int = 0
    matches: int = 0
    created: int = 0
    open_count: int = 0
    execution_mode: ExecutionMode = "SIMULATED"
    live_probes: bool = False
