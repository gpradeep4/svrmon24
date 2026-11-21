"""ITSM in-app notifications — ITSM DB only; best-effort emit helpers."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from ..models.notifications import (
    CHANNEL_IN_APP,
    NOTIFICATION_CHANNELS,
    NOTIFICATION_EVENT_TYPES,
    NOTIFICATION_STATUSES,
)
from .indexes import NOTIFICATIONS, ensure_itsm_indexes

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[NOTIFICATIONS]


def _new_notification_id() -> str:
    return f"NTF-{uuid.uuid4().hex[:10].upper()}"


def _actor_fields(actor: dict[str, Any] | None) -> dict[str, str | None]:
    actor = actor or {}
    return {
        "user_id": actor.get("user_id") or actor.get("username"),
        "username": actor.get("username") or actor.get("user_id"),
    }


def _clean_recipients(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= 50:
            break
    return out


def recipient_keys_for_user(
    *,
    user_id: str | None = None,
    username: str | None = None,
) -> list[str]:
    """Identity keys used to match inbox rows for the current principal."""
    keys: list[str] = []
    seen: set[str] = set()
    for raw in (user_id, username):
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        keys.append(item)
    return keys


def emit(
    *,
    tenant_id: str,
    event_type: str,
    recipient_user_ids: list[str] | None,
    subject: str,
    body: str,
    ticket_type: str | None = None,
    ticket_id: str | None = None,
    approval_id: str | None = None,
    tracking_id: str | None = None,
    channel: str = CHANNEL_IN_APP,
    actor: dict[str, Any] | None = None,
    exclude_actor: bool = True,
    fan_out_outbound: bool = True,
) -> list[dict[str, Any]]:
    """Create one in-app notification per recipient and fan-out outbound channels.

    Outbound email/sms/slack attempts are best-effort and never raise. When
    ``channel`` is an outbound channel (not ``in_app``), only that channel is
    attempted (no inbox row).
    """
    tid = require_tenant_id(tenant_id)
    if event_type not in NOTIFICATION_EVENT_TYPES:
        raise NotificationError(f"Invalid event_type '{event_type}'")
    if channel not in NOTIFICATION_CHANNELS:
        raise NotificationError(f"Invalid channel '{channel}'")

    recipients = _clean_recipients(recipient_user_ids)
    who = _actor_fields(actor)
    if exclude_actor and who["user_id"]:
        recipients = [r for r in recipients if r != who["user_id"] and r != who["username"]]
    if not recipients:
        return []

    subject_clean = (subject or "").strip() or "ITSM notification"
    body_clean = (body or "").strip() or subject_clean
    ticket_type_clean = (ticket_type or "").strip() or None
    ticket_id_clean = (ticket_id or "").strip() or None
    approval_clean = (approval_id or "").strip() or None
    tracking_clean = (tracking_id or "").strip() or None

    # Direct outbound-only emit (no inbox row).
    if channel != CHANNEL_IN_APP:
        from . import notification_delivery as delivery_service

        for recipient in recipients:
            try:
                delivery_service.deliver_one(
                    tenant_id=tid,
                    channel=channel,
                    recipient_user_id=recipient,
                    subject=subject_clean,
                    body=body_clean,
                    event_type=event_type,
                    ticket_type=ticket_type_clean,
                    ticket_id=ticket_id_clean,
                    approval_id=approval_clean,
                    tracking_id=tracking_clean,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "itsm outbound-only emit failed channel=%s event=%s tenant=%s",
                    channel,
                    event_type,
                    tid,
                )
        return []

    now = _now()
    docs: list[dict[str, Any]] = []
    for recipient in recipients:
        doc: dict[str, Any] = {
            "notification_id": _new_notification_id(),
            "channel": CHANNEL_IN_APP,
            "recipient_user_id": recipient,
            "recipients": list(recipients),
            "subject": subject_clean[:500],
            "body": body_clean[:4000],
            "ticket_type": ticket_type_clean,
            "ticket_id": ticket_id_clean,
            "approval_id": approval_clean,
            "tracking_id": tracking_clean,
            "status": "unread",
            "event_type": event_type,
            "created_at": now,
            "updated_at": now,
            "read_at": None,
            "archived_at": None,
            "actor_user_id": who["user_id"],
            "actor_username": who["username"],
        }
        stamp_tenant_id(doc, tenant_id=tid)
        docs.append(doc)

    if docs:
        _coll().insert_many(docs)
    serialized = [serialize_document(d) for d in docs]  # type: ignore[misc]

    if fan_out_outbound and serialized:
        try:
            from . import notification_delivery as delivery_service

            delivery_service.fan_out_from_in_app(
                tenant_id=tid,
                in_app_rows=serialized,  # type: ignore[arg-type]
                event_type=event_type,
                subject=subject_clean,
                body=body_clean,
                ticket_type=ticket_type_clean,
                ticket_id=ticket_id_clean,
                approval_id=approval_clean,
                tracking_id=tracking_clean,
            )
        except Exception:  # noqa: BLE001 — never break ticket mutations
            logger.exception(
                "itsm notification fan-out failed event=%s tenant=%s",
                event_type,
                tid,
            )

    return serialized


def emit_best_effort(**kwargs: Any) -> list[dict[str, Any]]:
    """Emit notifications without raising into callers (assign/status hooks)."""
    try:
        return emit(**kwargs)
    except Exception:  # noqa: BLE001 — never break ticket/approval/SLA flows
        logger.exception(
            "itsm notification emit failed event=%s tenant=%s",
            kwargs.get("event_type"),
            kwargs.get("tenant_id"),
        )
        return []


def list_inbox(
    *,
    tenant_id: str,
    recipient_keys: list[str],
    status: str | None = None,
    event_type: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    include_archived: bool = False,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    keys = _clean_recipients(recipient_keys)
    if not keys:
        return {
            "items": [],
            "count": 0,
            "total": 0,
            "page": 1,
            "page_size": page_size,
            "tenant_id": tid,
            "unread_count": 0,
        }

    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    clauses: list[dict[str, Any]] = [{"recipient_user_id": {"$in": keys}}]

    if status:
        if status not in NOTIFICATION_STATUSES:
            raise NotificationError(f"Invalid status '{status}'")
        clauses.append({"status": status})
    elif not include_archived:
        clauses.append({"status": {"$in": ["unread", "read"]}})

    if event_type:
        if event_type not in NOTIFICATION_EVENT_TYPES:
            raise NotificationError(f"Invalid event_type '{event_type}'")
        clauses.append({"event_type": event_type})

    scoped = merge_tenant_filter({"$and": clauses}, tid)
    allowed_sort = {"created_at", "updated_at", "status", "event_type", "subject"}
    sort_field = sort_by if sort_by in allowed_sort else "created_at"
    direction = DESCENDING if str(sort_dir).lower() != "asc" else ASCENDING

    coll = _coll()
    total = coll.count_documents(scoped)
    cursor = (
        coll.find(scoped)
        .sort([(sort_field, direction)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    unread = coll.count_documents(
        merge_tenant_filter(
            {"recipient_user_id": {"$in": keys}, "status": "unread"},
            tid,
        )
    )
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "tenant_id": tid,
        "unread_count": unread,
    }


def unread_count(*, tenant_id: str, recipient_keys: list[str]) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    keys = _clean_recipients(recipient_keys)
    if not keys:
        return {"unread_count": 0, "tenant_id": tid}
    count = _coll().count_documents(
        merge_tenant_filter(
            {"recipient_user_id": {"$in": keys}, "status": "unread"},
            tid,
        )
    )
    return {"unread_count": int(count), "tenant_id": tid}


def get_notification(
    notification_id: str,
    *,
    tenant_id: str,
    recipient_keys: list[str],
) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    keys = _clean_recipients(recipient_keys)
    if not keys:
        return None
    doc = _coll().find_one(
        {
            "tenant_id": tid,
            "notification_id": notification_id,
            "recipient_user_id": {"$in": keys},
        }
    )
    return serialize_document(doc)


def set_status(
    notification_id: str,
    *,
    tenant_id: str,
    recipient_keys: list[str],
    status: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if status not in NOTIFICATION_STATUSES:
        raise NotificationError(f"Invalid status '{status}'")
    keys = _clean_recipients(recipient_keys)
    if not keys:
        raise NotificationError("No recipient identity for inbox", status_code=403)

    existing = _coll().find_one(
        {
            "tenant_id": tid,
            "notification_id": notification_id,
            "recipient_user_id": {"$in": keys},
        }
    )
    if existing is None:
        raise NotificationError(
            f"Notification '{notification_id}' not found", status_code=404
        )

    now = _now()
    updates: dict[str, Any] = {"status": status, "updated_at": now}
    if status == "read":
        updates["read_at"] = now
        updates["archived_at"] = None
    elif status == "unread":
        updates["read_at"] = None
        updates["archived_at"] = None
    elif status == "archived":
        updates["archived_at"] = now
        if not existing.get("read_at"):
            updates["read_at"] = now

    doc = _coll().find_one_and_update(
        {
            "tenant_id": tid,
            "notification_id": notification_id,
            "recipient_user_id": {"$in": keys},
        },
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise NotificationError(
            f"Notification '{notification_id}' not found", status_code=404
        )
    return serialize_document(doc)  # type: ignore[return-value]


def _merge_recipients(
    primary: str | None, watchers: list[str] | None
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in [primary, *(watchers or [])]:
        item = str(raw or "").strip()
        if not item or item.lower() in seen:
            continue
        seen.add(item.lower())
        out.append(item)
    return out


def _notify_cc_emails(
    *,
    tenant_id: str,
    event_type: str,
    subject: str,
    body: str,
    ticket_type: str,
    ticket_id: str,
    cc_emails: list[str] | None,
    actor: dict[str, Any] | None,
) -> None:
    """Best-effort outbound email to CC addresses (no in-app inbox row)."""
    from . import notification_delivery as delivery_service

    for raw in cc_emails or []:
        addr = str(raw or "").strip()
        if not addr or "@" not in addr:
            continue
        try:
            delivery_service.deliver_one(
                tenant_id=tenant_id,
                channel="email",
                recipient_user_id=addr,
                subject=subject,
                body=body,
                event_type=event_type,
                ticket_type=ticket_type,
                ticket_id=ticket_id,
            )
        except Exception:  # noqa: BLE001 — never break ticket mutations
            logger.exception(
                "itsm cc email notify failed tenant=%s ticket=%s",
                tenant_id,
                ticket_id,
            )


def notify_assignment(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    assignee_user_id: str | None,
    number_display: str | None = None,
    actor: dict[str, Any] | None = None,
    watcher_user_ids: list[str] | None = None,
    cc_emails: list[str] | None = None,
) -> list[dict[str, Any]]:
    recipients = _merge_recipients(assignee_user_id, watcher_user_ids)
    label = number_display or ticket_id
    subject = f"Assigned: {label}"
    body = f"You were assigned to {ticket_type} {label}."
    rows: list[dict[str, Any]] = []
    if recipients:
        rows = emit_best_effort(
            tenant_id=tenant_id,
            event_type="assignment",
            recipient_user_ids=recipients,
            subject=subject,
            body=body,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            actor=actor,
        )
    _notify_cc_emails(
        tenant_id=tenant_id,
        event_type="assignment",
        subject=subject,
        body=body,
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        cc_emails=cc_emails,
        actor=actor,
    )
    return rows


def notify_status_change(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    from_status: str,
    to_status: str,
    assignee_user_id: str | None = None,
    number_display: str | None = None,
    actor: dict[str, Any] | None = None,
    watcher_user_ids: list[str] | None = None,
    cc_emails: list[str] | None = None,
) -> list[dict[str, Any]]:
    recipients = _merge_recipients(assignee_user_id, watcher_user_ids)
    label = number_display or ticket_id
    subject = f"Status: {label} → {to_status}"
    body = f"{ticket_type} {label} changed from {from_status} to {to_status}."
    rows: list[dict[str, Any]] = []
    if recipients:
        rows = emit_best_effort(
            tenant_id=tenant_id,
            event_type="status_change",
            recipient_user_ids=recipients,
            subject=subject,
            body=body,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            actor=actor,
        )
    _notify_cc_emails(
        tenant_id=tenant_id,
        event_type="status_change",
        subject=subject,
        body=body,
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        cc_emails=cc_emails,
        actor=actor,
    )
    return rows


def notify_approval_requested(
    *,
    tenant_id: str,
    approval_id: str,
    title: str,
    ticket_type: str,
    ticket_id: str,
    approver_user_ids: list[str] | None,
    actor: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return emit_best_effort(
        tenant_id=tenant_id,
        event_type="approval_requested",
        recipient_user_ids=approver_user_ids,
        subject=f"Approval requested: {title}",
        body=f"Approval {approval_id} needs a decision for {ticket_type} {ticket_id}.",
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        approval_id=approval_id,
        actor=actor,
    )


def notify_approval_decided(
    *,
    tenant_id: str,
    approval_id: str,
    title: str,
    ticket_type: str,
    ticket_id: str,
    decision: str,
    recipient_user_ids: list[str] | None,
    actor: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return emit_best_effort(
        tenant_id=tenant_id,
        event_type="approval_decided",
        recipient_user_ids=recipient_user_ids,
        subject=f"Approval {decision}: {title}",
        body=f"Approval {approval_id} was {decision} for {ticket_type} {ticket_id}.",
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        approval_id=approval_id,
        actor=actor,
    )


def notify_sla_breach(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
    tracking_id: str | None = None,
    metric: str | None = None,
    assignee_user_id: str | None = None,
    number_display: str | None = None,
) -> list[dict[str, Any]]:
    if not assignee_user_id or not str(assignee_user_id).strip():
        return []
    label = number_display or ticket_id
    metric_label = (metric or "SLA").strip() or "SLA"
    return emit_best_effort(
        tenant_id=tenant_id,
        event_type="sla_breach",
        recipient_user_ids=[str(assignee_user_id).strip()],
        subject=f"SLA breached: {label}",
        body=f"{metric_label} breached for {ticket_type} {label}.",
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        tracking_id=tracking_id,
        exclude_actor=False,
    )


def lookup_ticket_assignee(
    *,
    tenant_id: str,
    ticket_type: str,
    ticket_id: str,
) -> tuple[str | None, str | None]:
    """Return (assignee_user_id, number_display) for a ticket, or (None, None)."""
    from .indexes import CHANGES, INCIDENTS, PROBLEMS

    tid = require_tenant_id(tenant_id)
    mapping = {
        "incident": (INCIDENTS, "incident_id"),
        "change": (CHANGES, "change_id"),
        "problem": (PROBLEMS, "problem_id"),
    }
    entry = mapping.get(str(ticket_type or "").strip())
    if not entry or not ticket_id:
        return None, None
    coll_name, id_field = entry
    doc = require_itsm_database()[coll_name].find_one(
        {"tenant_id": tid, id_field: str(ticket_id).strip()},
        {"assignee_user_id": 1, "number_display": 1},
    )
    if not doc:
        return None, None
    assignee = doc.get("assignee_user_id")
    return (
        str(assignee).strip() if assignee else None,
        str(doc.get("number_display") or "") or None,
    )
