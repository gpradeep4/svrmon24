"""Tenant-scoped ticket attachments with size/type limits (ITSM DB Binary)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from bson.binary import Binary
from pymongo import DESCENDING
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import require_tenant_id, stamp_tenant_id
from ..models.common import TICKET_TYPES
from .indexes import (
    ATTACHMENTS,
    CHANGES,
    INCIDENTS,
    PROBLEMS,
    ensure_itsm_indexes,
)
from . import activities as activities_service

# 5 MiB hard cap per file.
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS_PER_TICKET = 25

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

_TICKET_META: dict[str, tuple[str, str]] = {
    "incident": (INCIDENTS, "incident_id"),
    "change": (CHANGES, "change_id"),
    "problem": (PROBLEMS, "problem_id"),
}


class AttachmentError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[ATTACHMENTS]


def _actor_fields(actor: dict[str, Any] | None) -> dict[str, str | None]:
    actor = actor or {}
    return {
        "user_id": actor.get("user_id") or actor.get("username"),
        "username": actor.get("username") or actor.get("user_id"),
    }


def _new_attachment_id() -> str:
    return f"ATT-{uuid.uuid4().hex[:12].upper()}"


def _assert_ticket(*, tenant_id: str, ticket_type: str, ticket_id: str) -> None:
    tid = require_tenant_id(tenant_id)
    ttype = (ticket_type or "").strip().lower()
    tid_key = (ticket_id or "").strip()
    if ttype not in TICKET_TYPES:
        raise AttachmentError(f"Invalid ticket_type '{ticket_type}'")
    if not tid_key:
        raise AttachmentError("ticket_id is required")
    coll_name, id_field = _TICKET_META[ttype]
    doc = require_itsm_database()[coll_name].find_one(
        {"tenant_id": tid, id_field: tid_key}, {"_id": 1}
    )
    if doc is None:
        raise AttachmentError(
            f"{ttype} '{tid_key}' not found", status_code=404
        )


def _normalize_content_type(content_type: str | None, filename: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if not ct or ct == "application/octet-stream":
        lower = (filename or "").lower()
        if lower.endswith(".pdf"):
            ct = "application/pdf"
        elif lower.endswith((".png",)):
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
        raise AttachmentError(
            f"Content type '{ct or 'unknown'}' is not allowed. "
            f"Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}"
        )
    return ct


def _public_row(doc: dict[str, Any]) -> dict[str, Any]:
    row = serialize_document(doc) or {}
    row.pop("content", None)
    row["has_content"] = True
    return row


def list_attachments(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _assert_ticket(tenant_id=tid, ticket_type=ticket_type, ticket_id=ticket_id)
    ttype = ticket_type.strip().lower()
    tid_key = ticket_id.strip()
    cursor = (
        _coll()
        .find(
            {"tenant_id": tid, "ticket_type": ttype, "ticket_id": tid_key},
            {"content": 0},
        )
        .sort("created_at", DESCENDING)
    )
    items = [serialize_document(d) for d in cursor]
    return {
        "items": items,
        "total": len(items),
        "tenant_id": tid,
        "ticket_type": ttype,
        "ticket_id": tid_key,
        "max_bytes": MAX_ATTACHMENT_BYTES,
        "allowed_content_types": sorted(ALLOWED_CONTENT_TYPES),
    }


def create_attachment(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    filename: str,
    content: bytes,
    content_type: str | None = None,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    _assert_ticket(tenant_id=tid, ticket_type=ticket_type, ticket_id=ticket_id)
    ttype = ticket_type.strip().lower()
    tid_key = ticket_id.strip()
    name = (filename or "").strip() or "attachment.bin"
    if len(name) > 255:
        name = name[:255]
    data = content or b""
    if len(data) == 0:
        raise AttachmentError("Attachment content is empty")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError(
            f"Attachment exceeds max size of {MAX_ATTACHMENT_BYTES} bytes",
            status_code=413,
        )
    ct = _normalize_content_type(content_type, name)

    count = _coll().count_documents(
        {"tenant_id": tid, "ticket_type": ttype, "ticket_id": tid_key}
    )
    if count >= MAX_ATTACHMENTS_PER_TICKET:
        raise AttachmentError(
            f"Ticket already has the maximum of {MAX_ATTACHMENTS_PER_TICKET} attachments"
        )

    who = _actor_fields(actor)
    now = _now()
    attachment_id = _new_attachment_id()
    doc: dict[str, Any] = {
        "attachment_id": attachment_id,
        "ticket_type": ttype,
        "ticket_id": tid_key,
        "filename": name,
        "content_type": ct,
        "size_bytes": len(data),
        "content": Binary(data),
        "created_at": now,
        "updated_at": now,
        "created_by": who["username"],
        "updated_by": who["username"],
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _coll().insert_one(doc)

    activities_service.append_activity(
        tenant_id=tid,
        ticket_type=ttype,
        ticket_id=tid_key,
        activity_type="attachment",
        message=f"Attachment uploaded: {name} ({len(data)} bytes)",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        to_value=attachment_id,
    )
    return _public_row(doc)


def get_attachment_meta(
    attachment_id: str, *, tenant_id: str
) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one(
        {"tenant_id": tid, "attachment_id": attachment_id},
        {"content": 0},
    )
    return serialize_document(doc) if doc else None  # type: ignore[return-value]


def download_attachment(
    attachment_id: str, *, tenant_id: str
) -> tuple[dict[str, Any], bytes]:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one({"tenant_id": tid, "attachment_id": attachment_id})
    if doc is None:
        raise AttachmentError(
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
    attachment_id: str,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one(
        {"tenant_id": tid, "attachment_id": attachment_id},
        {"content": 0},
    )
    if doc is None:
        raise AttachmentError(
            f"Attachment '{attachment_id}' not found", status_code=404
        )
    _coll().delete_one({"tenant_id": tid, "attachment_id": attachment_id})
    who = _actor_fields(actor)
    activities_service.append_activity(
        tenant_id=tid,
        ticket_type=str(doc.get("ticket_type")),
        ticket_id=str(doc.get("ticket_id")),
        activity_type="attachment",
        message=f"Attachment deleted: {doc.get('filename') or attachment_id}",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        from_value=attachment_id,
    )
    return {
        "ok": True,
        "attachment_id": attachment_id,
        "tenant_id": tid,
    }
