"""Custom entity table definitions and records.

Storage approach (documented):
  - ``cmdb_custom_table_definitions`` — one doc per ``(tenant_id, table_key)``
    with embedded column schema.
  - ``cmdb_custom_records`` — single multi-tenant data collection keyed by
    ``(tenant_id, table_key, record_id)`` (not one Mongo collection per table).

Reference fields store ``{ref_id, ref_table}``. ``ref_table`` is either a
built-in CMDB component type (Server/Network/…) or another custom ``table_key``.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .components import COMPONENT_TYPES


class CustomColumnType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"
    REFERENCE = "reference"


# Built-in CMDB types that reference fields / relationship ends may target.
BUILTIN_REF_TABLES: frozenset[str] = frozenset(COMPONENT_TYPES)

# table_key / column_key reserved names — never collide with typed CMDB.
RESERVED_TABLE_KEYS: frozenset[str] = frozenset(
    {
        *COMPONENT_TYPES,
        "components",
        "cmdb",
        "cmdb_servers",
        "cmdb_network",
        "cmdb_middleware",
        "cmdb_databases",
        "cmdb_applications",
        "cmdb_relationships",
        "cmdb_field_definitions",
        "cmdb_column_configurations",
        "cmdb_custom_table_definitions",
        "cmdb_custom_records",
        "relationships",
        "inventory",
        "servers",
        "network",
        "middleware",
        "databases",
        "applications",
    }
)

TABLE_KEY_PATTERN = r"^[a-z][a-z0-9_]*$"
COLUMN_KEY_PATTERN = r"^[a-z][a-z0-9_]*$"


def is_builtin_ref_table(ref_table: str | None) -> bool:
    return bool(ref_table) and ref_table in BUILTIN_REF_TABLES


def normalize_ref_value(value: Any) -> dict[str, str] | None:
    """Normalize a reference field value to ``{ref_id, ref_table}`` or None."""
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        raise ValueError(
            "reference values must be objects with ref_id and ref_table "
            "(string-only references are not accepted)"
        )
    if isinstance(value, dict):
        ref_id = str(value.get("ref_id") or value.get("record_id") or value.get("component_id") or "").strip()
        ref_table = str(value.get("ref_table") or value.get("table") or value.get("target_table") or "").strip()
        if not ref_id and not ref_table:
            return None
        if not ref_id or not ref_table:
            raise ValueError("reference requires both ref_id and ref_table")
        return {"ref_id": ref_id, "ref_table": ref_table}
    raise ValueError("reference value must be an object with ref_id and ref_table")


class CustomColumnDef(BaseModel):
    """One column inside a custom table definition."""

    model_config = ConfigDict(extra="forbid")

    column_key: str = Field(min_length=1, max_length=64, pattern=COLUMN_KEY_PATTERN)
    label: str = Field(min_length=1, max_length=128)
    field_type: CustomColumnType = CustomColumnType.STRING
    required: bool = False
    enum_values: list[str] = Field(default_factory=list)
    # When field_type=reference: CMDB component type or custom table_key.
    reference_table: str | None = Field(default=None, max_length=64)
    order: int = Field(default=0, ge=0, le=500)
    description: str | None = Field(default=None, max_length=512)
    active: bool = True

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("label cannot be blank")
        return cleaned

    @field_validator("description", "reference_table")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("enum_values")
    @classmethod
    def clean_enums(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            item = str(item).strip()
            if item and item not in cleaned:
                cleaned.append(item)
        return cleaned

    @model_validator(mode="after")
    def validate_type_constraints(self) -> CustomColumnDef:
        if self.field_type == CustomColumnType.ENUM and not self.enum_values:
            raise ValueError("enum columns require at least one enum_values entry")
        if self.field_type != CustomColumnType.ENUM and self.enum_values:
            raise ValueError("enum_values is only allowed for enum columns")
        if self.field_type == CustomColumnType.REFERENCE:
            if not self.reference_table:
                raise ValueError("reference columns require reference_table")
            if self.reference_table in RESERVED_TABLE_KEYS - BUILTIN_REF_TABLES:
                raise ValueError(
                    f"reference_table '{self.reference_table}' is reserved"
                )
        elif self.reference_table:
            raise ValueError("reference_table is only allowed for reference columns")
        return self


class CustomTableCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_key: str = Field(min_length=1, max_length=64, pattern=TABLE_KEY_PATTERN)
    label: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    columns: list[CustomColumnDef] = Field(default_factory=list)
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

    @field_validator("table_key")
    @classmethod
    def reject_reserved(cls, value: str) -> str:
        if value in RESERVED_TABLE_KEYS:
            raise ValueError(f"table_key '{value}' is reserved")
        return value

    @model_validator(mode="after")
    def unique_columns(self) -> CustomTableCreate:
        keys = [c.column_key for c in self.columns]
        if len(keys) != len(set(keys)):
            raise ValueError("columns must have unique column_key values")
        return self


class CustomTableUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=128)
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


class CustomColumnCreate(CustomColumnDef):
    """POST body for adding a column (same shape as CustomColumnDef)."""


class CustomColumnUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=128)
    field_type: CustomColumnType | None = None
    required: bool | None = None
    enum_values: list[str] | None = None
    reference_table: str | None = Field(default=None, max_length=64)
    order: int | None = Field(default=None, ge=0, le=500)
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

    @field_validator("description", "reference_table")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class CustomRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator("record_id", "display_name")
    @classmethod
    def strip_required_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value cannot be blank")
        return cleaned


class CustomRecordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    fields: dict[str, Any] | None = None

    @field_validator("display_name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("display_name cannot be blank")
        return cleaned


class CustomTableView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    table_key: str
    label: str
    description: str | None = None
    columns: list[dict[str, Any]] = Field(default_factory=list)
    active: bool = True
    tenant_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CustomRecordView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    record_id: str
    table_key: str
    display_name: str
    fields: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
