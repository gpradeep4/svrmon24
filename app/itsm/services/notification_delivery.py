"""Outbound notification delivery fan-out + delivery attempt log (ITSM DB).

Called from in-app ``emit`` as best-effort; never raises into ticket mutations.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, ReturnDocument
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import require_tenant_id, stamp_tenant_id
from ..models.notifications import OUTBOUND_CHANNELS
from . import notification_channels as channel_settings_service
from .indexes import NOTIFICATION_DELIVERIES, ensure_itsm_indexes
from .notification_providers import DeliveryResult, get_provider

logger = logging.getLogger(__name__)

# Backoff seconds by attempt number (1-based after failure).
_RETRY_BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 900, 1800, 3600)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _retry_at_for_attempt(attempt: int) -> datetime:
    idx = max(0, min(int(attempt) - 1, len(_RETRY_BACKOFF_SECONDS) - 1))
    return _now() + timedelta(seconds=_RETRY_BACKOFF_SECONDS[idx])


def _coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[NOTIFICATION_DELIVERIES]


def _new_delivery_id() -> str:
    return f"DLV-{uuid.uuid4().hex[:10].upper()}"


def _resolve_user_doc(recipient_key: str) -> dict[str, Any] | None:
    """Look up a platform user by user_id, username, or email."""
    from ...services import users as users_service

    key = (recipient_key or "").strip()
    if not key:
        return None
    doc = users_service.get_user(key)
    if doc:
        return doc
    doc = users_service.get_user_by_username(key)
    if doc:
        return doc
    if "@" in key:
        return users_service.get_user_by_email(key)
    return None


def _recipient_in_tenant(*, tenant_id: str, user_doc: dict[str, Any] | None) -> bool:
    """Deny delivery when the resolved user is not a member of the tenant."""
    if user_doc is None:
        # Free-string assignees (e.g. ops.alice in demos) are not platform users;
        # allow attempt but address resolution may skip. Tenant isolation for
        # *known* users is enforced below.
        return True
    from ...services import memberships as memberships_service

    user_id = str(user_doc.get("user_id") or "").strip()
    if not user_id:
        return False
    mem = memberships_service.get_membership_for_user_tenant(user_id, tenant_id)
    return mem is not None


def _address_for_channel(
    channel: str,
    *,
    user_doc: dict[str, Any] | None,
    recipient_key: str,
    channel_config: dict[str, Any],
) -> str | None:
    if channel == "email":
        if user_doc and user_doc.get("email"):
            return str(user_doc["email"]).strip()
        if "@" in (recipient_key or ""):
            return recipient_key.strip()
        return None
    if channel == "sms":
        # No phone field on users yet — scaffold uses empty → skipped.
        return None
    if channel == "slack":
        # Prefer explicit default channel; otherwise username as handle hint.
        default = str(channel_config.get("default_channel") or "").strip()
        if default:
            return default
        if user_doc and user_doc.get("username"):
            return str(user_doc["username"]).strip()
        return (recipient_key or "").strip() or None
    return None


def _record_attempt(
    *,
    tenant_id: str,
    channel: str,
    recipient_user_id: str,
    notification_id: str | None,
    event_type: str,
    subject: str,
    body: str,
    ticket_type: str | None,
    ticket_id: str | None,
    approval_id: str | None,
    tracking_id: str | None,
    result: DeliveryResult,
) -> dict[str, Any]:
    now = _now()
    doc: dict[str, Any] = {
        "delivery_id": _new_delivery_id(),
        "notification_id": notification_id,
        "channel": channel,
        "recipient_user_id": recipient_user_id,
        "recipient_address": result.recipient_address,
        "status": result.status,
        "attempt": 1,
        "provider": result.provider,
        "error": result.error,
        "detail": result.detail,
        "event_type": event_type,
        "subject": (subject or "")[:500],
        "body": (body or "")[:4000],
        "ticket_type": ticket_type,
        "ticket_id": ticket_id,
        "approval_id": approval_id,
        "tracking_id": tracking_id,
        "created_at": now,
        "updated_at": now,
        "next_retry_at": (
            _retry_at_for_attempt(1) if result.status == "failed" else None
        ),
    }
    stamp_tenant_id(doc, tenant_id=tenant_id)
    _coll().insert_one(doc)
    return serialize_document(doc)  # type: ignore[return-value]


def deliver_one(
    *,
    tenant_id: str,
    channel: str,
    recipient_user_id: str,
    subject: str,
    body: str,
    notification_id: str | None = None,
    event_type: str = "assignment",
    ticket_type: str | None = None,
    ticket_id: str | None = None,
    approval_id: str | None = None,
    tracking_id: str | None = None,
) -> dict[str, Any]:
    """Attempt one outbound delivery and persist the attempt row."""
    tid = require_tenant_id(tenant_id)
    if channel not in OUTBOUND_CHANNELS:
        result = DeliveryResult(
            status="skipped",
            provider="none",
            error=f"unknown_channel:{channel}",
        )
        return _record_attempt(
            tenant_id=tid,
            channel=channel,
            recipient_user_id=recipient_user_id,
            notification_id=notification_id,
            event_type=event_type,
            subject=subject,
            body=body,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            approval_id=approval_id,
            tracking_id=tracking_id,
            result=result,
        )

    settings = channel_settings_service.get_channel_settings(
        tenant_id=tid, channel=channel
    )
    if not settings.get("enabled"):
        result = DeliveryResult(
            status="skipped",
            provider="none",
            error="channel_disabled",
        )
        return _record_attempt(
            tenant_id=tid,
            channel=channel,
            recipient_user_id=recipient_user_id,
            notification_id=notification_id,
            event_type=event_type,
            subject=subject,
            body=body,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            approval_id=approval_id,
            tracking_id=tracking_id,
            result=result,
        )

    user_doc = _resolve_user_doc(recipient_user_id)
    if user_doc is not None and not _recipient_in_tenant(
        tenant_id=tid, user_doc=user_doc
    ):
        result = DeliveryResult(
            status="denied",
            provider="none",
            error="cross_tenant_recipient_denied",
            recipient_address=str(user_doc.get("email") or "") or None,
        )
        logger.info(
            "itsm delivery denied cross-tenant channel=%s recipient=%s tenant=%s",
            channel,
            recipient_user_id,
            tid,
        )
        return _record_attempt(
            tenant_id=tid,
            channel=channel,
            recipient_user_id=recipient_user_id,
            notification_id=notification_id,
            event_type=event_type,
            subject=subject,
            body=body,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            approval_id=approval_id,
            tracking_id=tracking_id,
            result=result,
        )

    address = _address_for_channel(
        channel,
        user_doc=user_doc,
        recipient_key=recipient_user_id,
        channel_config=settings,
    )
    provider = get_provider(channel)
    if provider is None:
        result = DeliveryResult(
            status="skipped",
            provider="none",
            recipient_address=address,
            error="provider_missing",
        )
    else:
        result = provider.deliver(
            recipient_address=address or "",
            subject=subject,
            body=body,
            channel_config=settings,
        )

    return _record_attempt(
        tenant_id=tid,
        channel=channel,
        recipient_user_id=recipient_user_id,
        notification_id=notification_id,
        event_type=event_type,
        subject=subject,
        body=body,
        ticket_type=ticket_type,
        ticket_id=ticket_id,
        approval_id=approval_id,
        tracking_id=tracking_id,
        result=result,
    )


def fan_out_from_in_app(
    *,
    tenant_id: str,
    in_app_rows: list[dict[str, Any]],
    event_type: str,
    subject: str,
    body: str,
    ticket_type: str | None = None,
    ticket_id: str | None = None,
    approval_id: str | None = None,
    tracking_id: str | None = None,
    channels: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Deliver outbound channels for each in-app notification recipient."""
    tid = require_tenant_id(tenant_id)
    targets = list(channels) if channels else list(OUTBOUND_CHANNELS)
    attempts: list[dict[str, Any]] = []
    for row in in_app_rows:
        recipient = str(row.get("recipient_user_id") or "").strip()
        if not recipient:
            continue
        notification_id = row.get("notification_id")
        for channel in targets:
            try:
                attempt = deliver_one(
                    tenant_id=tid,
                    channel=channel,
                    recipient_user_id=recipient,
                    subject=subject,
                    body=body,
                    notification_id=notification_id,
                    event_type=event_type,
                    ticket_type=ticket_type,
                    ticket_id=ticket_id,
                    approval_id=approval_id,
                    tracking_id=tracking_id,
                )
                attempts.append(attempt)
            except Exception:  # noqa: BLE001 — never break emit
                logger.exception(
                    "itsm delivery fan-out failed channel=%s recipient=%s tenant=%s",
                    channel,
                    recipient,
                    tid,
                )
    return attempts


def list_deliveries(
    *,
    tenant_id: str,
    channel: str | None = None,
    status: str | None = None,
    notification_id: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    query: dict[str, Any] = {"tenant_id": tid}
    if channel:
        query["channel"] = channel
    if status:
        query["status"] = status
    if notification_id:
        query["notification_id"] = notification_id
    coll = _coll()
    total = coll.count_documents(query)
    cursor = (
        coll.find(query)
        .sort([("created_at", -1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "tenant_id": tid,
    }


def _execute_provider_for_doc(doc: dict[str, Any]) -> DeliveryResult:
    """Re-run the channel provider for an existing delivery document."""
    tid = str(doc.get("tenant_id") or "")
    channel = str(doc.get("channel") or "")
    recipient = str(doc.get("recipient_user_id") or "")
    if channel not in OUTBOUND_CHANNELS:
        return DeliveryResult(
            status="skipped",
            provider="none",
            error=f"unknown_channel:{channel}",
        )
    settings = channel_settings_service.get_channel_settings(
        tenant_id=tid, channel=channel
    )
    if not settings.get("enabled"):
        return DeliveryResult(
            status="skipped",
            provider="none",
            error="channel_disabled",
        )
    user_doc = _resolve_user_doc(recipient)
    if user_doc is not None and not _recipient_in_tenant(
        tenant_id=tid, user_doc=user_doc
    ):
        return DeliveryResult(
            status="denied",
            provider="none",
            error="cross_tenant_recipient_denied",
            recipient_address=str(user_doc.get("email") or "") or None,
        )
    address = _address_for_channel(
        channel,
        user_doc=user_doc,
        recipient_key=recipient,
        channel_config=settings,
    )
    provider = get_provider(channel)
    if provider is None:
        return DeliveryResult(
            status="skipped",
            provider="none",
            recipient_address=address,
            error="provider_missing",
        )
    return provider.deliver(
        recipient_address=address or "",
        subject=str(doc.get("subject") or ""),
        body=str(doc.get("body") or ""),
        channel_config=settings,
    )


def retry_due_deliveries(
    *,
    query: dict[str, Any],
    limit: int = 100,
    max_attempts: int = 5,
) -> dict[str, Any]:
    """Retry failed deliveries matching ``query``; updates rows in place."""
    coll = _coll()
    limit = max(1, min(int(limit), 500))
    cursor = (
        coll.find(query)
        .sort([("next_retry_at", ASCENDING), ("created_at", ASCENDING)])
        .limit(limit)
    )
    scanned = 0
    retried = 0
    sent = 0
    failed = 0
    skipped = 0
    for doc in cursor:
        scanned += 1
        delivery_id = doc.get("delivery_id")
        tid = doc.get("tenant_id")
        if not delivery_id or not tid:
            continue
        attempt = int(doc.get("attempt") or 1) + 1
        if attempt > max_attempts:
            continue
        # Claim row so concurrent workers skip it.
        claimed = coll.find_one_and_update(
            {
                "tenant_id": tid,
                "delivery_id": delivery_id,
                "status": "failed",
                "attempt": {"$lt": max_attempts},
            },
            {
                "$set": {
                    "status": "pending",
                    "updated_at": _now(),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if claimed is None:
            continue
        retried += 1
        try:
            result = _execute_provider_for_doc(claimed)
        except Exception as exc:  # noqa: BLE001
            result = DeliveryResult(
                status="failed",
                provider=str(claimed.get("provider") or "none"),
                error=str(exc)[:500],
                recipient_address=claimed.get("recipient_address"),
            )
        updates: dict[str, Any] = {
            "status": result.status,
            "provider": result.provider,
            "error": result.error,
            "detail": result.detail,
            "recipient_address": result.recipient_address
            or claimed.get("recipient_address"),
            "attempt": attempt,
            "updated_at": _now(),
            "next_retry_at": (
                _retry_at_for_attempt(attempt) if result.status == "failed" else None
            ),
        }
        coll.update_one(
            {"tenant_id": tid, "delivery_id": delivery_id},
            {"$set": updates},
        )
        if result.status == "sent":
            sent += 1
        elif result.status == "failed":
            failed += 1
        else:
            skipped += 1
    return {
        "scanned": scanned,
        "retried": retried,
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
    }
