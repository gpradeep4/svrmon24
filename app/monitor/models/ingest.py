"""Live log ingest models — HTTP batches, ingest keys, syslog source maps."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .literals import CollectMode, DataSource, ExecutionMode
from .logs import LogSeverity, SourceKind

IngestKeyStatus = Literal["active", "revoked"]
SyslogSourceStatus = Literal["active", "quarantine", "disabled"]


class LogIngestEventItem(BaseModel):
    """One event in an HTTP ingest batch."""

    model_config = ConfigDict(extra="ignore")

    severity: LogSeverity = "info"
    message: str = Field(min_length=1, max_length=8192)
    observed_at: datetime | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    stream_id: str | None = None
    component_id: str | None = None
    target_id: str | None = None
    collect_mode: CollectMode | None = None


class LogIngestBatch(BaseModel):
    """POST /api/monitor/ingest/logs body."""

    model_config = ConfigDict(extra="ignore")

    stream_id: str | None = None
    events: list[LogIngestEventItem] = Field(default_factory=list)
    os_family: Literal["linux", "windows", "macos", "unix"] | None = None
    seq: int | None = Field(default=None, ge=1)


class LogIngestKeyCreate(BaseModel):
    """Admin create payload for an HTTP ingest key."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=128)
    stream_id: str | None = None


class LogIngestKey(BaseModel):
    """Stored ingest key metadata (never includes plaintext token)."""

    model_config = ConfigDict(extra="ignore")

    key_id: str
    name: str
    stream_id: str | None = None
    status: IngestKeyStatus = "active"
    tenant_id: str | None = None
    created_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class LogIngestKeyCreated(LogIngestKey):
    """Create response — plaintext token returned once."""

    token: str


class SyslogSource(BaseModel):
    """Map a syslog source IP/CIDR to a tenant log stream."""

    model_config = ConfigDict(extra="ignore")

    source_id: str
    source_ip: str
    stream_id: str
    status: SyslogSourceStatus = "active"
    label: str | None = None
    tenant_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SyslogSourceUpsert(BaseModel):
    """PUT body item for syslog source mapping."""

    model_config = ConfigDict(extra="ignore")

    source_ip: str = Field(min_length=1, max_length=64)
    stream_id: str = Field(min_length=1, max_length=64)
    status: SyslogSourceStatus = "active"
    label: str | None = Field(default=None, max_length=128)
    source_id: str | None = None


class SyslogSourcesPut(BaseModel):
    """Replace tenant syslog source mappings."""

    model_config = ConfigDict(extra="ignore")

    sources: list[SyslogSourceUpsert] = Field(default_factory=list)


class LogIngestResult(BaseModel):
    """HTTP ingest response summary."""

    model_config = ConfigDict(extra="ignore")

    ok: bool = True
    execution_mode: ExecutionMode = "LIVE"
    data_source: DataSource = "HTTP_INGEST"
    accepted: int = 0
    rejected: int = 0
    trimmed: int = 0
    tenant_id: str
    stream_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    live_probes: bool = True
    ingest_today: int | None = None
    ingest_limit: int | None = None


class MetricIngestSample(BaseModel):
    """One metric sample in an agent metrics batch."""

    model_config = ConfigDict(extra="ignore")

    metric_name: str = Field(min_length=1, max_length=128)
    value: float
    unit: str | None = Field(default=None, max_length=32)
    observed_at: datetime | None = None
    target_id: str | None = None
    component_id: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)


class MetricIngestBatch(BaseModel):
    """POST /api/monitor/ingest/metrics body (agent token)."""

    model_config = ConfigDict(extra="ignore")

    os_family: Literal["linux", "windows", "macos", "unix"] | None = None
    seq: int | None = Field(default=None, ge=1)
    samples: list[MetricIngestSample] = Field(default_factory=list)


class FileEventIngestItem(BaseModel):
    """One file-version event in an agent file-events batch."""

    model_config = ConfigDict(extra="ignore")

    watch_id: str | None = None
    path: str | None = Field(default=None, max_length=1024)
    label: str | None = Field(default=None, max_length=128)
    version: int | None = Field(default=None, ge=1)
    change_kind: Literal[
        "created", "modified", "renamed", "deleted", "permission"
    ] = "modified"
    actor: str | None = Field(default=None, max_length=128)
    actor_type: Literal["user", "service", "system"] = "service"
    changed_at: datetime | None = None
    observed_at: datetime | None = None
    summary: str | None = Field(default=None, max_length=512)
    content_hash: str | None = Field(default=None, max_length=128)
    size_bytes: int | None = Field(default=None, ge=0)
    component_id: str | None = None
    os_watcher: str | None = Field(default=None, max_length=64)


class FileEventIngestBatch(BaseModel):
    """POST /api/monitor/ingest/file-events body (agent token)."""

    model_config = ConfigDict(extra="ignore")

    os_family: Literal["linux", "windows", "macos", "unix"] | None = None
    seq: int | None = Field(default=None, ge=1)
    events: list[FileEventIngestItem] = Field(default_factory=list)


