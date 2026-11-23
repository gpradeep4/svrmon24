"""Catalog item + form schema models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CATALOG_DOMAINS: tuple[str, ...] = (
    "os",
    "middleware",
    "database",
    "networking",
    "cloud",
    "generic",
    "vulnerability",
    "other",
)
COLLECT_MODES: tuple[str, ...] = ("agentless", "agent")
CMDB_SYNC_MODES: tuple[str, ...] = ("none", "create", "update")
TARGET_PLACEMENTS: tuple[str, ...] = ("on_prem", "cloud", "either")
RISK_TIERS: tuple[str, ...] = ("low", "medium", "high")
FIELD_TYPES: tuple[str, ...] = (
    "string",
    "text",
    "integer",
    "number",
    "boolean",
    "enum",
    "ci_ref",
    "path",
    "username",
    "hostname",
    "ip",
    "datetime",
    "secret_ref",
    "cloud_account_ref",
    "cloud_region",
    "cloud_sku",
)

CatalogDomain = Literal[
    "os",
    "middleware",
    "database",
    "networking",
    "cloud",
    "generic",
    "vulnerability",
    "other",
]
CollectMode = Literal["agentless", "agent"]
CmdbSyncMode = Literal["none", "create", "update"]
TargetPlacement = Literal["on_prem", "cloud", "either"]
RiskTier = Literal["low", "medium", "high"]
ItsmChangeType = Literal["standard", "normal", "emergency"]


class FormFieldSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=200)
    required: bool = False
    default: Any = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=1)
    minimum: float | None = None
    maximum: float | None = None
    pattern: str | None = Field(default=None, max_length=512)
    options: list[str] = Field(default_factory=list)
    multi: bool = False
    component_types: list[str] = Field(default_factory=list)
    help: str | None = Field(default=None, max_length=1000)

    @field_validator("type")
    @classmethod
    def _type_ok(cls, value: str) -> str:
        if value not in FIELD_TYPES:
            raise ValueError(f"unsupported field type '{value}'")
        return value

    @field_validator("name")
    @classmethod
    def _name_ok(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.replace("_", "").isalnum():
            raise ValueError("field name must be alphanumeric/underscore")
        return cleaned


class FormSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1)
    fields: list[FormFieldSchema] = Field(default_factory=list)


class CatalogItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    domain: CatalogDomain
    action_key: str = Field(min_length=1, max_length=128)
    form_schema: FormSchema = Field(default_factory=FormSchema)
    change_type_key: str = Field(min_length=1, max_length=128)
    itsm_change_type: ItsmChangeType = "normal"
    change_workflow_key: str | None = Field(default=None, max_length=128)
    risk_tier: RiskTier = "medium"
    enabled: bool = True
    supports_dry_run: bool = True
    default_execution_mode: Literal["SIMULATED", "DRY_RUN", "LIVE"] = "SIMULATED"
    allowed_collect_modes: list[CollectMode] = Field(
        default_factory=lambda: ["agentless", "agent"]
    )
    default_collect_mode: CollectMode = "agentless"
    target_placement: TargetPlacement = "on_prem"
    cmdb_sync: CmdbSyncMode = "none"
    cmdb_component_type: str | None = Field(default=None, max_length=64)
    cmdb_field_map: dict[str, str] = Field(default_factory=dict)
    adapter: str = Field(min_length=1, max_length=64)
    schema_version: int = Field(default=1, ge=1)

    @field_validator("key", "action_key", "change_type_key", "adapter")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("allowed_collect_modes")
    @classmethod
    def _modes(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("allowed_collect_modes must not be empty")
        for mode in value:
            if mode not in COLLECT_MODES:
                raise ValueError(f"invalid collect mode '{mode}'")
        return list(dict.fromkeys(value))


class CatalogItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    form_schema: FormSchema | None = None
    change_type_key: str | None = Field(default=None, min_length=1, max_length=128)
    itsm_change_type: ItsmChangeType | None = None
    change_workflow_key: str | None = Field(default=None, max_length=128)
    risk_tier: RiskTier | None = None
    enabled: bool | None = None
    supports_dry_run: bool | None = None
    default_execution_mode: Literal["SIMULATED", "DRY_RUN", "LIVE"] | None = None
    allowed_collect_modes: list[CollectMode] | None = None
    default_collect_mode: CollectMode | None = None
    target_placement: TargetPlacement | None = None
    cmdb_sync: CmdbSyncMode | None = None
    cmdb_component_type: str | None = Field(default=None, max_length=64)
    cmdb_field_map: dict[str, str] | None = None
    schema_version: int | None = Field(default=None, ge=1)
