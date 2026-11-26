"""CMDB Contracts models (Contracts tab — C4).

Contracts are tenant-scoped CMDB records. CI linkage is via
``cmdb_ci_contract_links``. Optional ``itsm_change_ref`` is a deep link
only (renewal Change) — tickets stay in ITSM; no cross-DB joins.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .work_info import ItsmTicketRef


class ContractCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_type: str = Field(default="support", min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    start_date: date | None = None
    end_date: date | None = None
    status: str = Field(default="active", min_length=1, max_length=40)
    vendor: str | None = Field(default=None, max_length=200)
    external_ref: str | None = Field(default=None, max_length=120)
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    # Optional ITSM Change deep link for renewals (module must be "change").
    itsm_change_ref: ItsmTicketRef | None = None

    @field_validator("contract_type", "description", "status")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("vendor", "external_ref")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("itsm_change_ref")
    @classmethod
    def _change_module_only(cls, value: ItsmTicketRef | None) -> ItsmTicketRef | None:
        if value is None:
            return None
        if value.module != "change":
            raise ValueError("itsm_change_ref.module must be 'change'")
        return value


class ContractUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_type: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = Field(default=None, min_length=1, max_length=40)
    vendor: str | None = Field(default=None, max_length=200)
    external_ref: str | None = Field(default=None, max_length=120)
    custom_fields: dict[str, Any] | None = None
    itsm_change_ref: ItsmTicketRef | None = None

    @field_validator("contract_type", "description", "status")
    @classmethod
    def _strip_optional_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @field_validator("vendor", "external_ref")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("itsm_change_ref")
    @classmethod
    def _change_module_only(cls, value: ItsmTicketRef | None) -> ItsmTicketRef | None:
        if value is None:
            return None
        if value.module != "change":
            raise ValueError("itsm_change_ref.module must be 'change'")
        return value


class ContractLinkCreate(BaseModel):
    """Link an existing contract, or create+link when ``contract`` is set."""

    model_config = ConfigDict(extra="forbid")

    contract_id: str | None = Field(default=None, min_length=1, max_length=80)
    relationship_name: str = Field(default="related_to", min_length=1, max_length=100)
    # Inline create when linking a brand-new contract to this CI.
    contract: ContractCreate | None = None

    @field_validator("contract_id", "relationship_name")
    @classmethod
    def _strip_optional_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned

    @model_validator(mode="after")
    def _xor_contract(self) -> ContractLinkCreate:
        if not self.contract_id and self.contract is None:
            raise ValueError("provide contract_id or contract")
        if self.contract_id and self.contract is not None:
            raise ValueError("provide contract_id or contract, not both")
        return self


def _date_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10] if value else None


def to_contract_row(doc: dict[str, Any]) -> dict[str, Any]:
    ref = doc.get("itsm_change_ref")
    return {
        "contract_id": doc.get("contract_id"),
        "tenant_id": doc.get("tenant_id"),
        "contract_type": doc.get("contract_type"),
        "description": doc.get("description"),
        "start_date": _date_str(doc.get("start_date")),
        "end_date": _date_str(doc.get("end_date")),
        "status": doc.get("status"),
        "vendor": doc.get("vendor"),
        "external_ref": doc.get("external_ref"),
        "custom_fields": doc.get("custom_fields") or {},
        "itsm_change_ref": ref,
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def to_contract_link_row(
    link: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "link_id": link.get("link_id"),
        "tenant_id": link.get("tenant_id"),
        "component_id": link.get("component_id"),
        "contract_id": link.get("contract_id"),
        "relationship_name": link.get("relationship_name"),
        "created_at": link.get("created_at"),
        "updated_at": link.get("updated_at"),
    }
    if contract is not None:
        row["contract"] = to_contract_row(contract)
        # Flatten grid columns for convenience.
        row["relationship_type"] = link.get("relationship_name")
        row["request_type"] = contract.get("contract_type")
        row["description"] = contract.get("description")
        row["start_date"] = _date_str(contract.get("start_date"))
        row["end_date"] = _date_str(contract.get("end_date"))
        row["status"] = contract.get("status")
        row["itsm_change_ref"] = contract.get("itsm_change_ref")
    return row
