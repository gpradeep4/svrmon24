"""Pydantic models for CMDB inventory bulk edit, import, and export."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .components import COMPONENT_TYPES, ComponentStatus


class ComponentBulkUpdate(BaseModel):
    """Apply safe shared fields to many components (tenant-scoped)."""

    model_config = ConfigDict(extra="forbid")

    component_ids: list[str] = Field(min_length=1, max_length=500)
    status: ComponentStatus | None = None
    environment: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("component_ids")
    @classmethod
    def normalize_ids(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            cid = (raw or "").strip()
            if not cid or cid in seen:
                continue
            seen.add(cid)
            cleaned.append(cid)
        if not cleaned:
            raise ValueError("component_ids must contain at least one id")
        return cleaned

    @field_validator("environment")
    @classmethod
    def strip_environment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("environment cannot be blank")
        return cleaned

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> ComponentBulkUpdate:
        if self.status is None and self.environment is None:
            raise ValueError("Provide status and/or environment to update")
        return self


ExportFormat = Literal["csv", "xlsx"]


# Canonical importable field keys (API / ComponentCreate names).
IMPORTABLE_FIELDS: tuple[str, ...] = (
    "component_id",
    "component_type",
    "name",
    "environment",
    "status",
    "hostname",
    "ip_address",
    "os_family",
    "os_version",
    "product_type",
    "product_version",
    "instance_name",
    "domain_name",
    "host_server_id",
    "listen_address",
    "listen_port",
    "installation_path",
    "domain_home",
    "log_folder_path",
    "endpoint",
    "cluster_or_replication_details",
    "device_name",
    "device_type",
    "management_ip",
    "virtual_ip",
    "listener_port",
    "application_name",
    "application_type",
    "service_url",
    "business_criticality",
    "owner",
)

REQUIRED_IMPORT_FIELDS: frozenset[str] = frozenset(
    {"component_type", "name", "environment"}
)

FIELD_ALIASES: dict[str, str] = {
    "id": "component_id",
    "component id": "component_id",
    "componentid": "component_id",
    "type": "component_type",
    "component type": "component_type",
    "componenttype": "component_type",
    "env": "environment",
    "hostname / name": "name",
    "hostname/name": "name",
    "hostname or name": "name",
    "os family": "os_family",
    "os version": "os_version",
    "product type": "product_type",
    "product version": "product_version",
    "ip address": "ip_address",
    "ip": "ip_address",
    "listen port": "listen_port",
    "listener port": "listener_port",
    "device name": "device_name",
    "device type": "device_type",
    "management ip": "management_ip",
    "virtual ip": "virtual_ip",
    "application name": "application_name",
    "application type": "application_type",
    "service url": "service_url",
    "business criticality": "business_criticality",
    "host server id": "host_server_id",
    "listen address": "listen_address",
    "installation path": "installation_path",
    "domain home": "domain_home",
    "log folder path": "log_folder_path",
    "instance name": "instance_name",
    "domain name": "domain_name",
    "cluster or replication details": "cluster_or_replication_details",
}


def normalize_header(value: str) -> str:
    return " ".join((value or "").strip().lower().replace("_", " ").split())


def resolve_field_key(header: str) -> str | None:
    """Map a spreadsheet header to a canonical component field key."""
    raw = (header or "").strip()
    if not raw:
        return None
    if raw in IMPORTABLE_FIELDS:
        return raw
    normalized = normalize_header(raw)
    underscored = normalized.replace(" ", "_")
    if underscored in IMPORTABLE_FIELDS:
        return underscored
    return FIELD_ALIASES.get(normalized)


class ImportRowResult(BaseModel):
    row_number: int
    ok: bool
    errors: list[str] = Field(default_factory=list)
    component_id: str | None = None
    payload: dict[str, Any] | None = None


class ImportReport(BaseModel):
    dry_run: bool
    filename: str
    format: str
    headers: list[str]
    mapping: dict[str, str]
    total_rows: int
    valid_rows: int
    invalid_rows: int
    created: int = 0
    skipped: int = 0
    rows: list[ImportRowResult] = Field(default_factory=list)
    unmapped_headers: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
