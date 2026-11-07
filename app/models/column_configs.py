"""Tenant-scoped grid column configurations (Master Phase 8).

``cmdb_column_configurations`` stores visibility / order / width / pin for
Inventory and Relationships grids. Locked columns (OS/product pairs;
protocol + ports) must remain visible and never collapse into combined keys.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GridKey(str, Enum):
    INVENTORY = "inventory"
    RELATIONSHIPS = "relationships"


GRID_KEYS: frozenset[str] = frozenset(g.value for g in GridKey)

PinSide = Literal["left", "right"] | None


# Never hide / merge these Inventory columns.
LOCKED_INVENTORY_COLUMNS: frozenset[str] = frozenset(
    {
        "os_family",
        "os_version",
        "product_type",
        "product_version",
    }
)

# Never hide / merge these Relationships columns.
LOCKED_RELATIONSHIP_COLUMNS: frozenset[str] = frozenset(
    {
        "protocol",
        "source_port",
        "target_port",
    }
)

# Actions stay available for grid operations.
LOCKED_ALWAYS_COLUMNS: frozenset[str] = frozenset({"actions"})


def locked_columns_for_grid(grid_key: str) -> frozenset[str]:
    if grid_key == GridKey.INVENTORY.value:
        return LOCKED_INVENTORY_COLUMNS | LOCKED_ALWAYS_COLUMNS
    if grid_key == GridKey.RELATIONSHIPS.value:
        return LOCKED_RELATIONSHIP_COLUMNS | LOCKED_ALWAYS_COLUMNS
    return LOCKED_ALWAYS_COLUMNS


def default_inventory_columns() -> list[dict]:
    """Canonical Inventory columns — OS/product pairs stay separate."""
    specs = [
        ("component_id", "Component ID", True),
        ("hostname_or_name", "Hostname/Component Name", True),
        ("component_type", "Component Type", True),
        ("os_family", "OS Family", True),
        ("os_version", "OS Version", True),
        ("product_type", "Product Type", True),
        ("product_version", "Product Version", True),
        ("environment", "Environment", True),
        ("status", "Status", True),
        ("actions", "Actions", True),
    ]
    locked = locked_columns_for_grid(GridKey.INVENTORY.value)
    return [
        {
            "column_key": key,
            "label": label,
            "visible": visible,
            "order": idx,
            "width": None,
            "pinned": None,
            "locked": key in locked,
        }
        for idx, (key, label, visible) in enumerate(specs)
    ]


def default_relationship_columns() -> list[dict]:
    """Canonical Relationships columns — protocol/ports stay separate."""
    specs = [
        ("relationship_id", "Relationship ID", True),
        ("source_component_id", "Source", True),
        ("target_component_id", "Target", True),
        ("relationship_type", "Type", True),
        ("protocol", "Protocol", True),
        ("source_port", "Source Port", True),
        ("target_port", "Target Port", True),
        ("environment", "Environment", True),
        ("discovery_method", "Discovery", True),
        ("verification_status", "Verification", True),
        ("actions", "Actions", True),
    ]
    locked = locked_columns_for_grid(GridKey.RELATIONSHIPS.value)
    return [
        {
            "column_key": key,
            "label": label,
            "visible": visible,
            "order": idx,
            "width": None,
            "pinned": None,
            "locked": key in locked,
        }
        for idx, (key, label, visible) in enumerate(specs)
    ]


def default_columns_for_grid(grid_key: str) -> list[dict]:
    if grid_key == GridKey.INVENTORY.value:
        return default_inventory_columns()
    if grid_key == GridKey.RELATIONSHIPS.value:
        return default_relationship_columns()
    raise ValueError(f"Unknown grid_key: {grid_key}")


def catalog_keys_for_grid(grid_key: str) -> frozenset[str]:
    return frozenset(c["column_key"] for c in default_columns_for_grid(grid_key))


class ColumnSetting(BaseModel):
    """One column entry inside a grid configuration."""

    model_config = ConfigDict(extra="forbid")

    column_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    visible: bool = True
    order: int = Field(ge=0, le=500)
    width: int | None = Field(default=None, ge=40, le=1200)
    pinned: Literal["left", "right"] | None = None

    @field_validator("column_key")
    @classmethod
    def strip_key(cls, value: str) -> str:
        return value.strip()


class ColumnConfigurationUpdate(BaseModel):
    """PUT body — replace column settings for one grid."""

    model_config = ConfigDict(extra="forbid")

    columns: list[ColumnSetting] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_keys(self) -> ColumnConfigurationUpdate:
        keys = [c.column_key for c in self.columns]
        if len(keys) != len(set(keys)):
            raise ValueError("columns must have unique column_key values")
        return self


class ColumnConfiguration(BaseModel):
    """Serialized grid column configuration."""

    model_config = ConfigDict(extra="ignore")

    grid_key: str
    tenant_id: str | None = None
    columns: list[dict]
    is_default: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
