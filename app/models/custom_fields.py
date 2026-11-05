"""CMDB field definitions (custom + built-in OS/product fields).

Master Phase 7 evolves the legacy custom-field registry into tenant-scoped
``cmdb_field_definitions``. Built-in OS Family / OS Version and Product Type /
Product Version remain **separate** native fields (never collapsed). Custom
field **values** still live on component ``custom_fields`` dicts.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .components import COMPONENT_TYPES, ComponentType


class CustomFieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"


# Alias used by Phase 7 docs / APIs.
FieldType = CustomFieldType


class FieldOrigin(str, Enum):
    """Where the definition came from."""

    CUSTOM = "custom"
    BUILTIN = "builtin"


class FieldStorage(str, Enum):
    """Where component values for this field live."""

    CUSTOM_FIELDS = "custom_fields"  # component.custom_fields[field_key]
    NATIVE = "native"  # top-level typed attribute (os_family, …)


# Locked built-in field keys — never merge/collapse these.
BUILTIN_OS_FAMILY = "os_family"
BUILTIN_OS_VERSION = "os_version"
BUILTIN_PRODUCT_TYPE = "product_type"
BUILTIN_PRODUCT_VERSION = "product_version"

BUILTIN_FIELD_KEYS: frozenset[str] = frozenset(
    {
        BUILTIN_OS_FAMILY,
        BUILTIN_OS_VERSION,
        BUILTIN_PRODUCT_TYPE,
        BUILTIN_PRODUCT_VERSION,
    }
)


class CustomFieldCreate(BaseModel):
    """Create payload for **custom** field definitions (API)."""

    model_config = ConfigDict(extra="forbid")

    field_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=128)
    field_type: CustomFieldType = CustomFieldType.STRING
    applies_to: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Component types this field applies to, or ['*'] for all.",
    )
    required: bool = False
    enum_values: list[str] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=512)
    active: bool = True

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("label cannot be blank")
        return cleaned

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("applies_to")
    @classmethod
    def validate_applies_to(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("applies_to cannot be empty")
        cleaned: list[str] = []
        for item in value:
            item = item.strip()
            if item == "*":
                cleaned.append("*")
                continue
            if item not in COMPONENT_TYPES:
                raise ValueError(f"Unknown component type in applies_to: {item}")
            cleaned.append(item)
        if "*" in cleaned:
            return ["*"]
        return sorted(set(cleaned))

    @field_validator("field_key")
    @classmethod
    def reject_builtin_keys(cls, value: str) -> str:
        if value in BUILTIN_FIELD_KEYS:
            raise ValueError(
                f"field_key '{value}' is reserved for a built-in native field"
            )
        return value

    @model_validator(mode="after")
    def validate_enum(self) -> CustomFieldCreate:
        if self.field_type == CustomFieldType.ENUM and not self.enum_values:
            raise ValueError("enum_values required when field_type is enum")
        if self.field_type != CustomFieldType.ENUM and self.enum_values:
            raise ValueError("enum_values only allowed when field_type is enum")
        return self


# Phase 7 canonical create alias (same schema; custom-only via API).
CmdbFieldCreate = CustomFieldCreate


class CustomFieldUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=128)
    field_type: CustomFieldType | None = None
    applies_to: list[str] | None = None
    required: bool | None = None
    enum_values: list[str] | None = None
    description: str | None = Field(default=None, max_length=512)
    active: bool | None = None

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("label cannot be blank")
        return cleaned

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("applies_to")
    @classmethod
    def validate_applies_to(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return CustomFieldCreate.model_validate(
            {
                "field_key": "tmp_key",
                "label": "tmp",
                "applies_to": value,
            }
        ).applies_to


CmdbFieldUpdate = CustomFieldUpdate


class CustomFieldDefinition(BaseModel):
    """Serialized field definition (custom or built-in)."""

    model_config = ConfigDict(extra="ignore")

    field_key: str
    label: str
    field_type: CustomFieldType
    applies_to: list[str]
    required: bool = False
    enum_values: list[str] = Field(default_factory=list)
    origin: FieldOrigin = FieldOrigin.CUSTOM
    storage: FieldStorage = FieldStorage.CUSTOM_FIELDS
    description: str | None = None
    active: bool = True
    locked: bool = False
    tenant_id: str | None = None
    created_at: datetime
    updated_at: datetime


CmdbFieldDefinition = CustomFieldDefinition


def field_applies_to_type(definition: dict, component_type: ComponentType | str) -> bool:
    applies = definition.get("applies_to") or ["*"]
    if "*" in applies:
        return True
    ctype = component_type.value if isinstance(component_type, ComponentType) else component_type
    return ctype in applies


def builtin_field_specs() -> list[dict]:
    """Canonical built-in definitions — OS and product pairs stay separate."""
    return [
        {
            "field_key": BUILTIN_OS_FAMILY,
            "label": "OS Family",
            "field_type": CustomFieldType.STRING.value,
            "applies_to": [ComponentType.SERVER.value],
            "required": False,
            "enum_values": [],
            "origin": FieldOrigin.BUILTIN.value,
            "storage": FieldStorage.NATIVE.value,
            "description": "Operating system family (native Server attribute).",
            "active": True,
            "locked": True,
        },
        {
            "field_key": BUILTIN_OS_VERSION,
            "label": "OS Version",
            "field_type": CustomFieldType.STRING.value,
            "applies_to": [ComponentType.SERVER.value],
            "required": False,
            "enum_values": [],
            "origin": FieldOrigin.BUILTIN.value,
            "storage": FieldStorage.NATIVE.value,
            "description": "Operating system version (native Server attribute; separate from OS Family).",
            "active": True,
            "locked": True,
        },
        {
            "field_key": BUILTIN_PRODUCT_TYPE,
            "label": "Product Type",
            "field_type": CustomFieldType.STRING.value,
            "applies_to": [
                ComponentType.MIDDLEWARE.value,
                ComponentType.DATABASE.value,
            ],
            "required": False,
            "enum_values": [],
            "origin": FieldOrigin.BUILTIN.value,
            "storage": FieldStorage.NATIVE.value,
            "description": "Middleware/Database product type (native attribute; separate from Product Version).",
            "active": True,
            "locked": True,
        },
        {
            "field_key": BUILTIN_PRODUCT_VERSION,
            "label": "Product Version",
            "field_type": CustomFieldType.STRING.value,
            "applies_to": [
                ComponentType.MIDDLEWARE.value,
                ComponentType.DATABASE.value,
            ],
            "required": False,
            "enum_values": [],
            "origin": FieldOrigin.BUILTIN.value,
            "storage": FieldStorage.NATIVE.value,
            "description": "Middleware/Database product version (native attribute; separate from Product Type).",
            "active": True,
            "locked": True,
        },
    ]
