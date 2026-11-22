"""File Monitoring request/response models — SIMULATED default; LIVE watch modes (L6)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .literals import DataSource, ExecutionMode, WatchMode

WatchStatus = Literal["active", "paused", "error"]
ChangeKind = Literal["created", "modified", "renamed", "deleted", "permission"]
OsWatcher = Literal[
    "inotify",
    "readdirectorychanges",
    "fsevents",
    "kqueue_or_poll",
]


class FileWatchTarget(BaseModel):
    """A watched file or path (demo / SIMULATED by default)."""

    model_config = ConfigDict(extra="ignore")

    watch_id: str
    path: str
    label: str
    host: str | None = None
    component_id: str | None = None
    status: WatchStatus = "active"
    execution_mode: ExecutionMode = "SIMULATED"
    watch_mode: WatchMode = "SIMULATED"
    agent_id: str | None = None
    os_watcher: str | None = None
    # Agentless HTTP checksum poll (limited path — L6).
    poll_url: str | None = None
    poll_interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    poll_method: Literal["GET", "HEAD"] | None = None
    egress_allowlist: list[str] | None = None
    last_content_hash: str | None = None
    last_size_bytes: int | None = None
    last_polled_at: datetime | None = None
    latest_version: int = 0
    latest_actor: str | None = None
    latest_changed_at: datetime | None = None
    notes: str | None = None
    tenant_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FileWatchPatch(BaseModel):
    """PATCH /api/monitor/files/watches/{watch_id} — set live watch mode."""

    model_config = ConfigDict(extra="ignore")

    watch_mode: WatchMode | None = None
    agent_id: str | None = None
    os_watcher: OsWatcher | str | None = None
    status: WatchStatus | None = None
    label: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=512)
    poll_url: str | None = Field(default=None, max_length=2048)
    poll_interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    poll_method: Literal["GET", "HEAD"] | None = None
    egress_allowlist: list[str] | None = None


class FileVersionEvent(BaseModel):
    """One version / change event for a watched target."""

    model_config = ConfigDict(extra="ignore")

    event_id: str
    watch_id: str
    path: str
    version: int = Field(ge=1)
    change_kind: ChangeKind = "modified"
    actor: str
    actor_type: Literal["user", "service", "system"] = "user"
    changed_at: datetime
    summary: str
    content_hash: str | None = None
    size_bytes: int | None = None
    execution_mode: ExecutionMode = "SIMULATED"
    data_source: DataSource = "SYNTHETIC_DEMO"
    note: str = "Synthetic demo event — not a live filesystem change."
    agent_id: str | None = None
    os_watcher: str | None = None
    os_family: str | None = None
    tenant_id: str | None = None
    created_at: datetime | None = None
