"""CMDB CI Work Info + attachments (tenant-scoped, C3).

**Attachment storage strategy:** MongoDB Binary documents in
``cmdb_ci_attachments`` inside the CMDB database (``svrmon-cmdb``), mirroring
ITSM ticket attachments. Chosen because:

- No object-store / S3 dependency for self-hosted dual-ship
- Existing Binary + size/type-cap pattern in ``app/itsm/services/attachments.py``
- Tenant scoping via ``tenant_id`` on every doc; content never leaves CMDB DB
- Work-info rows hold ``attachment_ids`` only (no blob inline on the log doc)

Caps: 5 MiB / file, 10 attachments / work-info entry, allow-list content types.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from bson.binary import Binary
from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from ...db import require_database
from ...serialization import serialize_document
from ...tenancy import require_tenant_id, stamp_tenant_id
from ..models.work_info import (
    ViewAccess,
    WorkInfoCreate,
    WorkInfoUpdate,
    to_work_info_row,
)
from . import components as components_service

COLLECTION = "cmdb_ci_work_info"
ATTACHMENTS = "cmdb_ci_attachments"

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS_PER_WORK_INFO = 10

ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/json",
        "application/zip",
        "text/plain",
        "text/csv",
        "text/markdown",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    }
)


class WorkInfoError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _work_coll() -> Collection:
    coll = require_database()[COLLECTION]
    coll.create_index([("work_info_id", ASCENDING)], unique=True)
    coll.create_index(
        [("tenant_id", ASCENDING), ("component_id", ASCENDING)],
        name="tenant_component_idx",
    )
    coll.create_index(
        [("tenant_id", ASCENDING), ("component_id", ASCENDING), ("created_at", DESCENDING)],
        name="tenant_component_created_idx",
    )
    return coll


def _att_coll() -> Collection:
    coll = require_database()[ATTACHMENTS]
    coll.create_index([("attachment_id", ASCENDING)], unique=True)
    coll.create_index(
        [("tenant_id", ASCENDING), ("work_info_id", ASCENDING)],
        name="tenant_work_info_idx",
    )
    coll.create_index(
        [("tenant_id", ASCENDING), ("component_id", ASCENDING)],
        name="tenant_component_idx",
    )
    return coll


def _new_work_info_id() -> str:
    return f"wi-{uuid.uuid4().hex[:12]}"


def _new_attachment_id() -> str:
    return f"CATT-{uuid.uuid4().hex[:12].upper()}"


def _require_component(component_id: str, *, tenant_id: str) -> dict[str, Any]:
    doc = components_service.get_component(component_id, tenant_id=tenant_id)
    if doc is None:
        raise WorkInfoError(
            f"Component '{component_id}' not found", status_code=404
        )
    return doc


def _get_work_doc(
    component_id: str,
    work_info_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    doc = _work_coll().find_one(
        {
            "tenant_id": tenant_id,
            "component_id": component_id,
            "work_info_id": work_info_id,
        }
    )
    if doc is None:
        raise WorkInfoError(
            f"Work info '{work_info_id}' not found", status_code=404
        )
    return doc


def _actor_username(actor: dict[str, Any] | None) -> str | None:
    actor = actor or {}
    return actor.get("username") or actor.get("user_id")


def _normalize_content_type(content_type: str | None, filename: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if not ct or ct == "application/octet-stream":
        lower = (filename or "").lower()
        if lower.endswith(".pdf"):
            ct = "application/pdf"
        elif lower.endswith(".png"):
            ct = "image/png"
        elif lower.endswith((".jpg", ".jpeg")):
            ct = "image/jpeg"
        elif lower.endswith(".gif"):
            ct = "image/gif"
        elif lower.endswith(".webp"):
            ct = "image/webp"
        elif lower.endswith(".txt"):
            ct = "text/plain"
        elif lower.endswith(".csv"):
            ct = "text/csv"
        elif lower.endswith((".md", ".markdown")):
            ct = "text/markdown"
        elif lower.endswith(".json"):
            ct = "application/json"
        elif lower.endswith(".zip"):
            ct = "application/zip"
    if ct not in ALLOWED_CONTENT_TYPES:
        raise WorkInfoError(
            f"Content type '{ct or 'unknown'}' is not allowed. "
            f"Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}"
        )
    return ct


def _public_attachment(doc: dict[str, Any]) -> dict[str, Any]:
    row = serialize_document(doc) or {}
    row.pop("content", None)
    row["has_content"] = True
    return row


def list_work_info(
    component_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    cursor = (
        _work_coll()
        .find({"tenant_id": tid, "component_id": component_id})
        .sort("created_at", DESCENDING)
    )
    items = [to_work_info_row(serialize_document(d) or d) for d in cursor]
    return {
        "items": items,
        "total": len(items),
        "component_id": component_id,
        "tenant_id": tid,
    }


def get_work_info(
    component_id: str,
    work_info_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    doc = _get_work_doc(component_id, work_info_id, tenant_id=tid)
    row = to_work_info_row(serialize_document(doc) or doc)
    # Enrich with attachment metadata (no binary).
    aids = list(doc.get("attachment_ids") or [])
    attachments: list[dict[str, Any]] = []
    if aids:
        for adoc in _att_coll().find(
            {
                "tenant_id": tid,
                "work_info_id": work_info_id,
                "attachment_id": {"$in": aids},
            },
            {"content": 0},
        ):
            attachments.append(_public_attachment(adoc))
    row["attachments"] = attachments
    return row


def create_work_info(
    component_id: str,
    payload: WorkInfoCreate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    now = _now()
    work_info_id = _new_work_info_id()
    ref = None
    if payload.itsm_ticket_ref is not None:
        ref = payload.itsm_ticket_ref.model_dump()
    doc: dict[str, Any] = {
        "work_info_id": work_info_id,
        "component_id": component_id,
        "work_info_type": payload.work_info_type,
        "source": payload.source,
        "summary": payload.summary,
        "notes": payload.notes,
        "locked": bool(payload.locked),
        "view_access": payload.view_access.value
        if isinstance(payload.view_access, ViewAccess)
        else str(payload.view_access),
        "attachment_ids": [],
        "itsm_ticket_ref": ref,
        "created_by": _actor_username(actor),
        "created_at": now,
        "updated_at": now,
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _work_coll().insert_one(doc)
    return to_work_info_row(serialize_document(doc) or doc)


def update_work_info(
    component_id: str,
    work_info_id: str,
    payload: WorkInfoUpdate,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    existing = _get_work_doc(component_id, work_info_id, tenant_id=tid)
    if existing.get("locked"):
        raise WorkInfoError(
            f"Work info '{work_info_id}' is locked and cannot be modified",
            status_code=409,
        )
    updates = payload.model_dump(exclude_unset=True)
    if "view_access" in updates and updates["view_access"] is not None:
        va = updates["view_access"]
        updates["view_access"] = va.value if hasattr(va, "value") else va
    if "itsm_ticket_ref" in updates and updates["itsm_ticket_ref"] is not None:
        ref = updates["itsm_ticket_ref"]
        updates["itsm_ticket_ref"] = (
            ref if isinstance(ref, dict) else ref.model_dump()
        )
    updates["updated_at"] = _now()
    _work_coll().update_one(
        {
            "tenant_id": tid,
            "component_id": component_id,
            "work_info_id": work_info_id,
        },
        {"$set": updates},
    )
    return get_work_info(component_id, work_info_id, tenant_id=tid)


def delete_work_info(
    component_id: str,
    work_info_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    existing = _get_work_doc(component_id, work_info_id, tenant_id=tid)
    if existing.get("locked"):
        raise WorkInfoError(
            f"Work info '{work_info_id}' is locked and cannot be deleted",
            status_code=409,
        )
    # Cascade attachment blobs for this work-info entry.
    _att_coll().delete_many(
        {"tenant_id": tid, "work_info_id": work_info_id, "component_id": component_id}
    )
    _work_coll().delete_one(
        {
            "tenant_id": tid,
            "component_id": component_id,
            "work_info_id": work_info_id,
        }
    )
    return {
        "ok": True,
        "work_info_id": work_info_id,
        "component_id": component_id,
        "tenant_id": tid,
    }


def add_attachment(
    component_id: str,
    work_info_id: str,
    *,
    tenant_id: str,
    filename: str,
    content: bytes,
    content_type: str | None = None,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    existing = _get_work_doc(component_id, work_info_id, tenant_id=tid)
    if existing.get("locked"):
        raise WorkInfoError(
            f"Work info '{work_info_id}' is locked; attachments cannot be added",
            status_code=409,
        )
    name = (filename or "").strip() or "attachment.bin"
    if len(name) > 255:
        name = name[:255]
    data = content or b""
    if len(data) == 0:
        raise WorkInfoError("Attachment content is empty")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise WorkInfoError(
            f"Attachment exceeds max size of {MAX_ATTACHMENT_BYTES} bytes",
            status_code=413,
        )
    ct = _normalize_content_type(content_type, name)
    aids = list(existing.get("attachment_ids") or [])
    if len(aids) >= MAX_ATTACHMENTS_PER_WORK_INFO:
        raise WorkInfoError(
            f"Work info already has the maximum of "
            f"{MAX_ATTACHMENTS_PER_WORK_INFO} attachments"
        )

    now = _now()
    attachment_id = _new_attachment_id()
    adoc: dict[str, Any] = {
        "attachment_id": attachment_id,
        "work_info_id": work_info_id,
        "component_id": component_id,
        "filename": name,
        "content_type": ct,
        "size_bytes": len(data),
        "content": Binary(data),
        "created_at": now,
        "updated_at": now,
        "created_by": _actor_username(actor),
    }
    stamp_tenant_id(adoc, tenant_id=tid)
    _att_coll().insert_one(adoc)
    aids.append(attachment_id)
    _work_coll().update_one(
        {
            "tenant_id": tid,
            "component_id": component_id,
            "work_info_id": work_info_id,
        },
        {"$set": {"attachment_ids": aids, "updated_at": now}},
    )
    return _public_attachment(adoc)


def download_attachment(
    component_id: str,
    work_info_id: str,
    attachment_id: str,
    *,
    tenant_id: str,
) -> tuple[dict[str, Any], bytes]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    _get_work_doc(component_id, work_info_id, tenant_id=tid)
    doc = _att_coll().find_one(
        {
            "tenant_id": tid,
            "component_id": component_id,
            "work_info_id": work_info_id,
            "attachment_id": attachment_id,
        }
    )
    if doc is None:
        raise WorkInfoError(
            f"Attachment '{attachment_id}' not found", status_code=404
        )
    raw = doc.get("content")
    if isinstance(raw, Binary):
        data = bytes(raw)
    elif isinstance(raw, (bytes, bytearray)):
        data = bytes(raw)
    else:
        data = b""
    meta = serialize_document({k: v for k, v in doc.items() if k != "content"})
    return meta or {}, data


def delete_attachment(
    component_id: str,
    work_info_id: str,
    attachment_id: str,
    *,
    tenant_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _require_component(component_id, tenant_id=tid)
    existing = _get_work_doc(component_id, work_info_id, tenant_id=tid)
    if existing.get("locked"):
        raise WorkInfoError(
            f"Work info '{work_info_id}' is locked; attachments cannot be removed",
            status_code=409,
        )
    result = _att_coll().delete_one(
        {
            "tenant_id": tid,
            "component_id": component_id,
            "work_info_id": work_info_id,
            "attachment_id": attachment_id,
        }
    )
    if result.deleted_count == 0:
        raise WorkInfoError(
            f"Attachment '{attachment_id}' not found", status_code=404
        )
    aids = [a for a in (existing.get("attachment_ids") or []) if a != attachment_id]
    _work_coll().update_one(
        {
            "tenant_id": tid,
            "component_id": component_id,
            "work_info_id": work_info_id,
        },
        {"$set": {"attachment_ids": aids, "updated_at": _now()}},
    )
    return {
        "ok": True,
        "attachment_id": attachment_id,
        "work_info_id": work_info_id,
        "tenant_id": tid,
    }
