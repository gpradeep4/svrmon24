"""CMDB component models — common + type-specific fields."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ComponentType(str, Enum):
    SERVER = "Server"
    NETWORK = "Network"
    MIDDLEWARE = "Middleware"
    DATABASE = "Database"
    APPLICATION = "Application"


COMPONENT_TYPES: tuple[str, ...] = tuple(t.value for t in ComponentType)


class ComponentStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DECOMMISSIONED = "decommissioned"
    UNKNOWN = "unknown"


class ServerFields(BaseModel):
    hostname: str | None = None
    ip_address: str | None = None
    os_family: str | None = None
    os_version: str | None = None


class MiddlewareFields(BaseModel):
    product_type: str | None = None
    product_version: str | None = None
    instance_name: str | None = None
    domain_name: str | None = None
    host_server_id: str | None = None
    listen_address: str | None = None
    listen_port: int | None = None
    installation_path: str | None = None
    domain_home: str | None = None
    log_folder_path: str | None = None


class DatabaseFields(BaseModel):
    product_type: str | None = None
    product_version: str | None = None
    instance_name: str | None = None
    endpoint: str | None = None
    listen_port: int | None = None
    cluster_or_replication_details: str | None = None
    log_folder_path: str | None = None


class NetworkFields(BaseModel):
    device_name: str | None = None
    device_type: str | None = None
    management_ip: str | None = None
    virtual_ip: str | None = None
    listener_port: int | None = None


class ApplicationFields(BaseModel):
    application_name: str | None = None
    application_type: str | None = None
    service_url: str | None = None
    business_criticality: str | None = None
    owner: str | None = None


_TYPE_FIELD_MODELS: dict[ComponentType, type[BaseModel]] = {
    ComponentType.SERVER: ServerFields,
    ComponentType.MIDDLEWARE: MiddlewareFields,
    ComponentType.DATABASE: DatabaseFields,
    ComponentType.NETWORK: NetworkFields,
    ComponentType.APPLICATION: ApplicationFields,
}

# Flat keys allowed per type (for validation / filtering unknown attrs)
TYPE_SPECIFIC_KEYS: dict[ComponentType, frozenset[str]] = {
    ctype: frozenset(model.model_fields.keys()) for ctype, model in _TYPE_FIELD_MODELS.items()
}

ALL_TYPE_SPECIFIC_KEYS: frozenset[str] = frozenset().union(*TYPE_SPECIFIC_KEYS.values())


def _empty_type_fields(component_type: ComponentType) -> dict[str, Any]:
    return {key: None for key in TYPE_SPECIFIC_KEYS[component_type]}


class ComponentCreate(BaseModel):
    """Payload to create a CMDB component."""

    model_config = ConfigDict(extra="forbid")

    component_id: str | None = Field(
        default=None,
        description="Stable unique ID. Auto-generated when omitted.",
        min_length=1,
        max_length=128,
    )
    component_type: ComponentType
    name: str = Field(min_length=1, max_length=256)
    environment: str = Field(min_length=1, max_length=128)
    status: ComponentStatus = ComponentStatus.ACTIVE
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    # Server
    hostname: str | None = None
    ip_address: str | None = None
    os_family: str | None = None
    os_version: str | None = None

    # Middleware / Database shared product fields
    product_type: str | None = None
    product_version: str | None = None
    instance_name: str | None = None
    domain_name: str | None = None
    host_server_id: str | None = None
    listen_address: str | None = None
    listen_port: int | None = None
    installation_path: str | None = None
    domain_home: str | None = None
    log_folder_path: str | None = None

    # Database
    endpoint: str | None = None
    cluster_or_replication_details: str | None = None

    # Network
    device_name: str | None = None
    device_type: str | None = None
    management_ip: str | None = None
    virtual_ip: str | None = None
    listener_port: int | None = None

    # Application
    application_name: str | None = None
    application_type: str | None = None
    service_url: str | None = None
    business_criticality: str | None = None
    owner: str | None = None

    @field_validator("component_id")
    @classmethod
    def strip_component_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("component_id cannot be blank")
        return cleaned

    @field_validator("name", "environment")
    @classmethod
    def strip_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_type_specific_fields(self) -> ComponentCreate:
        allowed = TYPE_SPECIFIC_KEYS[self.component_type]
        provided = {
            key: getattr(self, key)
            for key in ALL_TYPE_SPECIFIC_KEYS
            if getattr(self, key) is not None
        }
        unexpected = set(provided) - set(allowed)
        if unexpected:
            raise ValueError(
                f"Fields {sorted(unexpected)} are not valid for component_type "
                f"{self.component_type.value}"
            )
        return self


class ComponentUpdate(BaseModel):
    """Partial update payload. component_id and component_type are immutable."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=256)
    environment: str | None = Field(default=None, min_length=1, max_length=128)
    status: ComponentStatus | None = None
    custom_fields: dict[str, Any] | None = None

    hostname: str | None = None
    ip_address: str | None = None
    os_family: str | None = None
    os_version: str | None = None
    product_type: str | None = None
    product_version: str | None = None
    instance_name: str | None = None
    domain_name: str | None = None
    host_server_id: str | None = None
    listen_address: str | None = None
    listen_port: int | None = None
    installation_path: str | None = None
    domain_home: str | None = None
    log_folder_path: str | None = None
    endpoint: str | None = None
    cluster_or_replication_details: str | None = None
    device_name: str | None = None
    device_type: str | None = None
    management_ip: str | None = None
    virtual_ip: str | None = None
    listener_port: int | None = None
    application_name: str | None = None
    application_type: str | None = None
    service_url: str | None = None
    business_criticality: str | None = None
    owner: str | None = None

    @field_validator("name", "environment")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be blank")
        return cleaned


class ComponentView(BaseModel):
    """Full component document returned by the API."""

    model_config = ConfigDict(extra="ignore")

    component_id: str
    component_type: ComponentType
    name: str
    environment: str
    status: ComponentStatus
    created_at: datetime
    updated_at: datetime
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    hostname: str | None = None
    ip_address: str | None = None
    os_family: str | None = None
    os_version: str | None = None
    product_type: str | None = None
    product_version: str | None = None
    instance_name: str | None = None
    domain_name: str | None = None
    host_server_id: str | None = None
    listen_address: str | None = None
    listen_port: int | None = None
    installation_path: str | None = None
    domain_home: str | None = None
    log_folder_path: str | None = None
    endpoint: str | None = None
    cluster_or_replication_details: str | None = None
    device_name: str | None = None
    device_type: str | None = None
    management_ip: str | None = None
    virtual_ip: str | None = None
    listener_port: int | None = None
    application_name: str | None = None
    application_type: str | None = None
    service_url: str | None = None
    business_criticality: str | None = None
    owner: str | None = None


class InventoryRow(BaseModel):
    """Inventory table row — columns stay separate (never combined)."""

    component_id: str
    hostname_or_name: str
    component_type: str
    os_family: str  # dash when N/A
    os_version: str
    product_type: str
    product_version: str
    environment: str
    status: str


def display_or_dash(value: Any) -> str:
    """Render a value for inventory/UI; empty/None → em dash."""
    if value is None:
        return "—"
    if isinstance(value, str) and not value.strip():
        return "—"
    return str(value)


def to_inventory_row(doc: dict[str, Any]) -> InventoryRow:
    """Map a stored component document to inventory columns."""
    ctype = doc.get("component_type")
    hostname = doc.get("hostname")
    name = doc.get("name") or ""
    if ctype == ComponentType.SERVER.value and hostname:
        hostname_or_name = str(hostname)
    elif ctype == ComponentType.NETWORK.value and doc.get("device_name"):
        hostname_or_name = str(doc.get("device_name"))
    elif ctype == ComponentType.APPLICATION.value and doc.get("application_name"):
        hostname_or_name = str(doc.get("application_name"))
    else:
        hostname_or_name = name or display_or_dash(hostname)

    return InventoryRow(
        component_id=str(doc.get("component_id") or ""),
        hostname_or_name=hostname_or_name or "—",
        component_type=display_or_dash(ctype),
        os_family=display_or_dash(doc.get("os_family")),
        os_version=display_or_dash(doc.get("os_version")),
        product_type=display_or_dash(doc.get("product_type")),
        product_version=display_or_dash(doc.get("product_version")),
        environment=display_or_dash(doc.get("environment")),
        status=display_or_dash(doc.get("status")),
    )


def build_component_document(
    payload: ComponentCreate,
    *,
    component_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Build a MongoDB document from a create payload."""
    doc: dict[str, Any] = {
        "component_id": component_id,
        "component_type": payload.component_type.value,
        "name": payload.name,
        "environment": payload.environment,
        "status": payload.status.value,
        "custom_fields": dict(payload.custom_fields or {}),
        "created_at": now,
        "updated_at": now,
    }
    # Ensure all type-specific keys exist (None for N/A) for stable reads/columns
    for ctype, keys in TYPE_SPECIFIC_KEYS.items():
        for key in keys:
            if key not in doc:
                doc[key] = None
    for key in TYPE_SPECIFIC_KEYS[payload.component_type]:
        doc[key] = getattr(payload, key)
    return doc


def apply_component_update(
    existing: dict[str, Any],
    payload: ComponentUpdate,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Apply a partial update onto an existing document."""
    ctype = ComponentType(existing["component_type"])
    data = payload.model_dump(exclude_unset=True)

    if "custom_fields" in data and data["custom_fields"] is not None:
        existing["custom_fields"] = dict(data.pop("custom_fields"))

    if "name" in data:
        existing["name"] = data.pop("name")
    if "environment" in data:
        existing["environment"] = data.pop("environment")
    if "status" in data and data["status"] is not None:
        status = data.pop("status")
        existing["status"] = status.value if isinstance(status, ComponentStatus) else status

    allowed = TYPE_SPECIFIC_KEYS[ctype]
    unexpected = set(data) - set(allowed)
    # Ignore None-clears for keys not belonging to this type only if they weren't set;
    # reject explicitly setting foreign type fields
    foreign_set = {
        key for key, value in data.items() if key not in allowed and value is not None
    }
    if foreign_set:
        raise ValueError(
            f"Fields {sorted(foreign_set)} are not valid for component_type {ctype.value}"
        )

    for key, value in data.items():
        if key in allowed:
            existing[key] = value

    existing["updated_at"] = now
    return existing


DeleteConfirmAction = Literal["check", "confirm"]
