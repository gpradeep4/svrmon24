"""CMDB Impacted Areas models (Helix Impacted Areas tab — C4).

Org/geo scope rows linked to a CI. Company codes are free-text in C4
(tenant dictionaries deferred).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _strip_opt(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class ImpactedAreaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    site_group: str | None = Field(default=None, max_length=120)
    site: str | None = Field(default=None, max_length=120)
    organization: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)

    @field_validator(
        "company",
        "region",
        "site_group",
        "site",
        "organization",
        "department",
    )
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _strip_opt(value)

    @model_validator(mode="after")
    def _at_least_one(self) -> ImpactedAreaCreate:
        fields = (
            self.company,
            self.region,
            self.site_group,
            self.site,
            self.organization,
            self.department,
        )
        if not any(fields):
            raise ValueError("at least one of company/region/site_group/site/organization/department is required")
        return self


class ImpactedAreaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    site_group: str | None = Field(default=None, max_length=120)
    site: str | None = Field(default=None, max_length=120)
    organization: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)

    @field_validator(
        "company",
        "region",
        "site_group",
        "site",
        "organization",
        "department",
    )
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _strip_opt(value)


def to_impacted_area_row(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "area_id": doc.get("area_id"),
        "tenant_id": doc.get("tenant_id"),
        "component_id": doc.get("component_id"),
        "company": doc.get("company"),
        "region": doc.get("region"),
        "site_group": doc.get("site_group"),
        "site": doc.get("site"),
        "organization": doc.get("organization"),
        "department": doc.get("department"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }
