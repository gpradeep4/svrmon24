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
    """Stored status values — map-only (Helix Deployed → active via UI labels later)."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DECOMMISSIONED = "decommissioned"
    UNKNOWN = "unknown"


class SupportedFlag(str, Enum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class ImpactLevel(str, Enum):
    """ITSM-aligned impact (1 = highest)."""

    ONE = "1"
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"


class UrgencyLevel(str, Enum):
    """ITSM-aligned urgency (1 = highest)."""

    ONE = "1"
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"


class PriorityLevel(str, Enum):
    """ITSM-aligned priority (1 = highest; Helix sample PRIORITY_5 → \"5\")."""

    ONE = "1"
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"


class ProductCategorization(BaseModel):
    """Optional three-tier product categorization (General tab)."""

    model_config = ConfigDict(extra="forbid")

    tier1: str | None = None
    tier2: str | None = None
    tier3: str | None = None

    @field_validator("tier1", "tier2", "tier3")
    @classmethod
    def strip_tiers(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CiLifecycle(BaseModel):
    """Optional lifecycle dates (General tab) — nested for consistency."""

    model_config = ConfigDict(extra="forbid")

    ordered_at: datetime | None = None
    received_at: datetime | None = None
    installed_at: datetime | None = None
    retirement_date: datetime | None = None


# Shared optional header + General natives on every typed CI document.
COMMON_OPTIONAL_KEYS: frozenset[str] = frozenset(
    {
        # Header
        "description",
        "tag_number",
        "serial_number",
        "part_number",
        "supported",
        "inventory_name",
        "company",
        "system_role",
        "status_reason",
        "impact",
        "urgency",
        "priority",
        "users_affected",
        "additional_information",
        # General
        "manufacturer",
        "model",
        "product_categorization",
        "lifecycle",
    }
)


class ServerFields(BaseModel):
    hostname: str | None = None
    ip_address: str | None = None
    os_family: str | None = None
    os_version: str | None = None
    # Helix Specifications natives (Computer System)
    system_type: str | None = None
    virtual_system_type: str | None = None
    is_virtual: bool | None = None
    impact_computation_model: str | None = None
    reset_capability: str | None = None
    dns_hostname: str | None = None
    domain: str | None = None
    workgroup: str | None = None
    total_physical_memory_mb: int | None = Field(default=None, ge=0)
    flash_memory_mb: int | None = Field(default=None, ge=0)


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


def _strip_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _dump_nested(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    return value


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

    # Shared header (optional)
    description: str | None = Field(default=None, max_length=512)
    tag_number: str | None = Field(default=None, max_length=128)
    serial_number: str | None = Field(default=None, max_length=256)
    part_number: str | None = Field(default=None, max_length=128)
    supported: SupportedFlag | None = None
    inventory_name: str | None = Field(default=None, max_length=256)
    company: str | None = Field(default=None, max_length=128)
    system_role: str | None = Field(default=None, max_length=128)
    status_reason: str | None = Field(default=None, max_length=256)
    impact: ImpactLevel | None = None
    urgency: UrgencyLevel | None = None
    priority: PriorityLevel | None = None
    users_affected: int | None = Field(default=None, ge=0)
    additional_information: str | None = Field(default=None, max_length=4096)

    # Shared General (optional)
    manufacturer: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=256)
    product_categorization: ProductCategorization | None = None
    lifecycle: CiLifecycle | None = None

    # Server
    hostname: str | None = None
    ip_address: str | None = None
    os_family: str | None = None
    os_version: str | None = None
    system_type: str | None = None
    virtual_system_type: str | None = None
    is_virtual: bool | None = None
    impact_computation_model: str | None = None
    reset_capability: str | None = None
    dns_hostname: str | None = None
    domain: str | None = None
    workgroup: str | None = None
    total_physical_memory_mb: int | None = Field(default=None, ge=0)
    flash_memory_mb: int | None = Field(default=None, ge=0)

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

    @field_validator(
        "description",
        "tag_number",
        "serial_number",
        "part_number",
        "inventory_name",
        "company",
        "system_role",
        "status_reason",
        "additional_information",
        "manufacturer",
        "model",
        "system_type",
        "virtual_system_type",
        "impact_computation_model",
        "reset_capability",
        "dns_hostname",
        "domain",
        "workgroup",
    )
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        return _strip_optional_str(value)

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

    description: str | None = Field(default=None, max_length=512)
    tag_number: str | None = Field(default=None, max_length=128)
    serial_number: str | None = Field(default=None, max_length=256)
    part_number: str | None = Field(default=None, max_length=128)
    supported: SupportedFlag | None = None
    inventory_name: str | None = Field(default=None, max_length=256)
    company: str | None = Field(default=None, max_length=128)
    system_role: str | None = Field(default=None, max_length=128)
    status_reason: str | None = Field(default=None, max_length=256)
    impact: ImpactLevel | None = None
    urgency: UrgencyLevel | None = None
    priority: PriorityLevel | None = None
    users_affected: int | None = Field(default=None, ge=0)
    additional_information: str | None = Field(default=None, max_length=4096)

    manufacturer: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=256)
    product_categorization: ProductCategorization | None = None
    lifecycle: CiLifecycle | None = None

    hostname: str | None = None
    ip_address: str | None = None
    os_family: str | None = None
    os_version: str | None = None
    system_type: str | None = None
    virtual_system_type: str | None = None
    is_virtual: bool | None = None
    impact_computation_model: str | None = None
    reset_capability: str | None = None
    dns_hostname: str | None = None
    domain: str | None = None
    workgroup: str | None = None
    total_physical_memory_mb: int | None = Field(default=None, ge=0)
    flash_memory_mb: int | None = Field(default=None, ge=0)
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

    @field_validator(
        "description",
        "tag_number",
        "serial_number",
        "part_number",
        "inventory_name",
        "company",
        "system_role",
        "status_reason",
        "additional_information",
        "manufacturer",
        "model",
        "system_type",
        "virtual_system_type",
        "impact_computation_model",
        "reset_capability",
        "dns_hostname",
        "domain",
        "workgroup",
    )
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        return _strip_optional_str(value)


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

    description: str | None = None
    tag_number: str | None = None
    serial_number: str | None = None
    part_number: str | None = None
    supported: SupportedFlag | None = None
    inventory_name: str | None = None
    company: str | None = None
    system_role: str | None = None
    status_reason: str | None = None
    impact: ImpactLevel | None = None
    urgency: UrgencyLevel | None = None
    priority: PriorityLevel | None = None
    users_affected: int | None = None
    additional_information: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    product_categorization: ProductCategorization | None = None
    lifecycle: CiLifecycle | None = None

    hostname: str | None = None
    ip_address: str | None = None
    os_family: str | None = None
    os_version: str | None = None
    system_type: str | None = None
    virtual_system_type: str | None = None
    is_virtual: bool | None = None
    impact_computation_model: str | None = None
    reset_capability: str | None = None
    dns_hostname: str | None = None
    domain: str | None = None
    workgroup: str | None = None
    total_physical_memory_mb: int | None = None
    flash_memory_mb: int | None = None
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
    custom_fields: dict[str, Any] = Field(default_factory=dict)


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

    raw_cf = doc.get("custom_fields") or {}
    custom_fields = dict(raw_cf) if isinstance(raw_cf, dict) else {}

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
        custom_fields=custom_fields,
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
    # Shared optional header / General — always present (null when unset)
    for key in COMMON_OPTIONAL_KEYS:
        value = getattr(payload, key)
        if key in {"supported", "impact", "urgency", "priority"}:
            doc[key] = _enum_value(value)
        elif key in {"product_categorization", "lifecycle"}:
            doc[key] = _dump_nested(value)
        else:
            doc[key] = value
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
    elif "status" in data:
        data.pop("status")

    for key in list(data.keys()):
        if key not in COMMON_OPTIONAL_KEYS:
            continue
        value = data.pop(key)
        if key in {"supported", "impact", "urgency", "priority"}:
            existing[key] = _enum_value(value)
        elif key in {"product_categorization", "lifecycle"}:
            existing[key] = _dump_nested(value)
        else:
            existing[key] = value

    allowed = TYPE_SPECIFIC_KEYS[ctype]
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
