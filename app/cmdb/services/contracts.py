"""CMDB Contracts + CI contract links (tenant-scoped, C4)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from ...db import require_database
from ...serialization import serialize_document
from ...tenancy import require_tenant_id, stamp_tenant_id
from ..models.contracts import (
    ContractCreate,
    ContractLinkCreate,
    ContractUpdate,
    to_contract_link_row,
    to_contract_row,
)
from . import components as components_service

CONTRACTS_COLLECTION = "cmdb_contracts"
LINKS_COLLECTION = "cmdb_ci_contract_links"


class ContractError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _contracts() -> Collection:
    coll = require_database()[CONTRACTS_COLLECTION]
    coll.create_index([("contract_id", ASCENDING)], unique=True)
    coll.create_index(
        [("tenant_id", ASCENDING), ("status", ASCENDING)],
        name="tenant_status_idx",
    )
    coll.create_index(
        [("tenant_id", ASCENDING), ("updated_at", DESCENDING)],
        name="tenant_updated_idx",
    )
    return coll


def _links() -> Collection:
    coll = require_database()[LINKS_COLLECTION]
    coll.create_index([("link_id", ASCENDING)], unique=True)
    coll.create_index(
        [("tenant_id", ASCENDING), ("component_id", ASCENDING)],
        name="tenant_component_idx",
    )
    coll.create_index(
        [
            ("tenant_id", ASCENDING),
            ("component_id", ASCENDING),
            ("contract_id", ASCENDING),
        ],
        name="tenant_component_contract_uq",
        unique=True,
    )
    return coll


def _new_contract_id() -> str:
    return f"ctr-{uuid.uuid4().hex[:12]}"


def _new_link_id() -> str:
    return f"clk-{uuid.uuid4().hex[:12]}"


def _require_component(component_id: str, *, tenant_id: str) -> dict[str, Any]:
    doc = components_service.get_component(component_id, tenant_id=tenant_id)
    if doc is None:
        raise ContractError(
            f"Component '{component_id}' not found", status_code=404
        )
    return doc


def _serialize_ref(ref: Any) -> dict[str, str] | None:
    if ref is None:
        return None
    if hasattr(ref, "model_dump"):
        return ref.model_dump()
    if isinstance(ref, dict):
        return {"module": ref["module"], "ticket_id": ref["ticket_id"]}
    return None


def _date_value(value: date | None) -> date | None:
    return value


def create_contract(payload: ContractCreate, *, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    now = _now()
    contract_id = _new_contract_id()
    doc: dict[str, Any] = {
        "contract_id": contract_id,
        "contract_type": payload.contract_type,
        "description": payload.description,
        "start_date": _date_value(payload.start_date),
        "end_date": _date_value(payload.end_date),
        "status": payload.status,
        "vendor": payload.vendor,
        "external_ref": payload.external_ref,
        "custom_fields": dict(payload.custom_fields or {}),
        "itsm_change_ref": _serialize_ref(payload.itsm_change_ref),
        "created_at": now,
        "updated_at": now,
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _contracts().insert_one(doc)
    return to_contract_row(serialize_document(doc) or doc)


def get_contract(contract_id: str, *, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    doc = _contracts().find_one({"tenant_id": tid, "contract_id": contract_id})
    if doc is None:
        raise ContractError(f"Contract '{contract_id}' not found", status_code=404)
    return to_contract_row(serialize_document(doc) or doc)


def list_contracts(
    *,
    tenant_id: str,
    q: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    query: dict[str, Any] = {"tenant_id": tid}
    if status:
        query["status"] = status.strip()
    if q:
        needle = q.strip()
        if needle:
            query["$or"] = [
                {"description": {"$regex": needle, "$options": "i"}},
                {"vendor": {"$regex": needle, "$options": "i"}},
                {"external_ref": {"$regex": needle, "$options": "i"}},
                {"contract_id": {"$regex": needle, "$options": "i"}},
            ]
    lim = max(1, min(int(limit or 50), 200))
    cursor = (
        _contracts()
        .find(query)
        .sort([("updated_at", DESCENDING)])
        .limit(lim)
    )
    items = [to_contract_row(serialize_document(d) or d) for d in cursor]
    return {"items": items, "total": len(items), "tenant_id": tid}


def update_contract(
    contract_id: str,
    payload: ContractUpdate,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    coll = _contracts()
    existing = coll.find_one({"tenant_id": tid, "contract_id": contract_id})
    if existing is None:
        raise ContractError(f"Contract '{contract_id}' not found", status_code=404)

    updates = payload.model_dump(exclude_unset=True)
    if "itsm_change_ref" in updates:
        updates["itsm_change_ref"] = _serialize_ref(updates.get("itsm_change_ref"))
    if not updates:
        return to_contract_row(serialize_document(existing) or existing)

    updates["updated_at"] = _now()
    coll.update_one(
        {"tenant_id": tid, "contract_id": contract_id},
        {"$set": updates},
    )
    doc = coll.find_one({"tenant_id": tid, "contract_id": contract_id})
    return to_contract_row(serialize_document(doc) or doc or {})


def delete_contract(contract_id: str, *, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    linked = _links().count_documents(
        {"tenant_id": tid, "contract_id": contract_id}
    )
    if linked:
        raise ContractError(
            f"Contract '{contract_id}' still linked to {linked} CI(s); unlink first",
            status_code=409,
        )
    result = _contracts().delete_one(
        {"tenant_id": tid, "contract_id": contract_id}
    )
    if result.deleted_count == 0:
        raise ContractError(f"Contract '{contract_id}' not found", status_code=404)
    return {"ok": True, "contract_id": contract_id, "tenant_id": tid}


def list_ci_contracts(component_id: str, *, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    links = list(
        _links()
        .find({"tenant_id": tid, "component_id": component_id})
        .sort([("updated_at", DESCENDING)])
    )
    items: list[dict[str, Any]] = []
    for link in links:
        link_doc = serialize_document(link) or link
        contract = _contracts().find_one(
            {"tenant_id": tid, "contract_id": link_doc.get("contract_id")}
        )
        contract_doc = (
            serialize_document(contract) or contract if contract else None
        )
        items.append(to_contract_link_row(link_doc, contract_doc))
    return {
        "items": items,
        "total": len(items),
        "component_id": component_id,
        "tenant_id": tid,
    }


def link_contract_to_ci(
    component_id: str,
    payload: ContractLinkCreate,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)

    if payload.contract is not None:
        created = create_contract(payload.contract, tenant_id=tid)
        contract_id = created["contract_id"]
        contract_doc = created
    else:
        assert payload.contract_id
        contract_doc = get_contract(payload.contract_id, tenant_id=tid)
        contract_id = payload.contract_id

    existing = _links().find_one(
        {
            "tenant_id": tid,
            "component_id": component_id,
            "contract_id": contract_id,
        }
    )
    if existing is not None:
        raise ContractError(
            f"Contract '{contract_id}' already linked to this CI",
            status_code=409,
        )

    now = _now()
    link_id = _new_link_id()
    link: dict[str, Any] = {
        "link_id": link_id,
        "component_id": component_id,
        "contract_id": contract_id,
        "relationship_name": payload.relationship_name,
        "created_at": now,
        "updated_at": now,
    }
    stamp_tenant_id(link, tenant_id=tid)
    _links().insert_one(link)
    return to_contract_link_row(
        serialize_document(link) or link,
        contract_doc if isinstance(contract_doc, dict) else None,
    )


def unlink_contract_from_ci(
    component_id: str,
    link_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    result = _links().delete_one(
        {"tenant_id": tid, "component_id": component_id, "link_id": link_id}
    )
    if result.deleted_count == 0:
        raise ContractError(f"Contract link '{link_id}' not found", status_code=404)
    return {
        "ok": True,
        "link_id": link_id,
        "component_id": component_id,
        "tenant_id": tid,
    }
