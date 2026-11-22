"""Monitor agent registration + enrollment models (L4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AgentStatus = Literal["pending", "active", "revoked", "stale"]
OsFamily = Literal["linux", "windows", "macos", "unix"]


class AgentEnrollmentCreate(BaseModel):
    """Admin create payload for a one-time enrollment code."""

    model_config = ConfigDict(extra="ignore")

    label: str | None = Field(default=None, max_length=128)
    ttl_seconds: int | None = Field(default=None, ge=60, le=86_400)


class AgentEnrollment(BaseModel):
    """Stored enrollment metadata (never includes plaintext code)."""

    model_config = ConfigDict(extra="ignore")

    enrollment_id: str
    label: str | None = None
    status: Literal["pending", "consumed", "expired"] = "pending"
    expires_at: datetime
    created_by: str | None = None
    created_at: datetime | None = None
    consumed_at: datetime | None = None
    consumed_by_agent_id: str | None = None
    tenant_id: str | None = None


class AgentEnrollmentCreated(AgentEnrollment):
    """Create response — plaintext enrollment code returned once."""

    code: str


class AgentRegisterRequest(BaseModel):
    """Agent exchanges a one-time enrollment code for an agent_id + token."""

    model_config = ConfigDict(extra="ignore")

    enrollment_code: str = Field(min_length=8, max_length=256)
    name: str = Field(min_length=1, max_length=128)
    hostname: str | None = Field(default=None, max_length=255)
    os_family: OsFamily = "linux"
    os_name: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=64)
    labels: dict[str, str] = Field(default_factory=dict)
    mtls_fingerprint: str | None = Field(default=None, max_length=128)


class AgentHeartbeatRequest(BaseModel):
    """Heartbeat payload from a registered agent."""

    model_config = ConfigDict(extra="ignore")

    version: str | None = Field(default=None, max_length=64)
    hostname: str | None = Field(default=None, max_length=255)
    labels: dict[str, str] | None = None
    status_note: str | None = Field(default=None, max_length=256)


class MonitorAgent(BaseModel):
    """Stored agent registry row (never includes plaintext token)."""

    model_config = ConfigDict(extra="ignore")

    agent_id: str
    name: str
    os_family: OsFamily = "linux"
    os_name: str | None = None
    hostname: str | None = None
    version: str | None = None
    status: AgentStatus = "pending"
    mtls_fingerprint: str | None = None
    last_seen_at: datetime | None = None
    labels: dict[str, Any] = Field(default_factory=dict)
    enrollment_id: str | None = None
    created_at: datetime | None = None
    revoked_at: datetime | None = None
    tenant_id: str | None = None


class MonitorAgentRegistered(MonitorAgent):
    """Register / rotate response — plaintext bearer token returned once."""

    token: str


class AgentTokenRotateResult(BaseModel):
    """Rotate-token response."""

    model_config = ConfigDict(extra="ignore")

    agent_id: str
    token: str
    status: AgentStatus = "active"
    rotated_at: datetime
    tenant_id: str


class AgentDesiredState(BaseModel):
    """Minimal desired-state returned to agents (watch/stream/target ids)."""

    model_config = ConfigDict(extra="ignore")

    agent_id: str
    tenant_id: str
    os_family: OsFamily | None = None
    os_watcher: str | None = None
    watch_ids: list[str] = Field(default_factory=list)
    stream_ids: list[str] = Field(default_factory=list)
    target_ids: list[str] = Field(default_factory=list)


class AgentDesiredStatePatch(BaseModel):
    """Admin PATCH body for agent desired-state lists."""

    model_config = ConfigDict(extra="ignore")

    watch_ids: list[str] | None = None
    stream_ids: list[str] | None = None
    target_ids: list[str] | None = None
