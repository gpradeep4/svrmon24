"""Configurable custom-field definitions for CMDB components."""

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


class CustomFieldCreate(BaseModel):
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

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("label cannot be blank")
        return cleaned

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
        # normalize: if * present, just *
        if "*" in cleaned:
            return ["*"]
        return sorted(set(cleaned))

    @model_validator(mode="after")
    def validate_enum(self) -> CustomFieldCreate:
        if self.field_type == CustomFieldType.ENUM and not self.enum_values:
            raise ValueError("enum_values required when field_type is enum")
        if self.field_type != CustomFieldType.ENUM and self.enum_values:
            raise ValueError("enum_values only allowed when field_type is enum")
        return self


class CustomFieldUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=128)
    field_type: CustomFieldType | None = None
    applies_to: list[str] | None = None
    required: bool | None = None
    enum_values: list[str] | None = None

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("label cannot be blank")
        return cleaned

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


class CustomFieldDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field_key: str
    label: str
    field_type: CustomFieldType
    applies_to: list[str]
    required: bool = False
    enum_values: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


def field_applies_to_type(definition: dict, component_type: ComponentType | str) -> bool:
    applies = definition.get("applies_to") or ["*"]
    if "*" in applies:
        return True
    ctype = component_type.value if isinstance(component_type, ComponentType) else component_type
    return ctype in applies
