"""Tenant-scoped outbound notification channel settings (ITSM DB).

Secrets are stored only as environment variable *names* (env refs).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, ReturnDocument
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import require_tenant_id, stamp_tenant_id
from ..models.notifications import (
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    CHANNEL_SLACK,
    OUTBOUND_CHANNELS,
)
from .indexes import NOTIFICATION_CHANNEL_SETTINGS, ensure_itsm_indexes
from .notification_providers import ProviderError, normalize_env_ref

logger = logging.getLogger(__name__)


class ChannelSettingsError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[NOTIFICATION_CHANNEL_SETTINGS]


def _default_doc(tenant_id: str, channel: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "channel": channel,
        "enabled": False,
        "created_at": _now(),
        "updated_at": _now(),
        "updated_by_user_id": None,
        "updated_by_username": None,
    }
    stamp_tenant_id(base, tenant_id=tenant_id)
    if channel == CHANNEL_EMAIL:
        base.update(
            {
                "smtp_host": None,
                "smtp_port": 587,
                "smtp_use_tls": True,
                "smtp_username": None,
                "smtp_password_env_ref": None,
                "from_address": None,
            }
        )
    elif channel == CHANNEL_SMS:
        base.update(
            {
                "twilio_account_sid_env_ref": None,
                "twilio_auth_token_env_ref": None,
                "twilio_from_number": None,
            }
        )
    elif channel == CHANNEL_SLACK:
        base.update(
            {
                "webhook_url_env_ref": None,
                "bot_token_env_ref": None,
                "default_channel": None,
            }
        )
    return base


def _public_view(doc: dict[str, Any] | None, *, channel: str, tenant_id: str) -> dict[str, Any]:
    if doc is None:
        doc = _default_doc(tenant_id, channel)
    row = serialize_document(doc) or dict(doc)
    # Never expose resolved secrets — only env ref names.
    return row


def get_channel_settings(*, tenant_id: str, channel: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if channel not in OUTBOUND_CHANNELS:
        raise ChannelSettingsError(f"Invalid channel '{channel}'", status_code=422)
    doc = _coll().find_one({"tenant_id": tid, "channel": channel})
    return _public_view(doc, channel=channel, tenant_id=tid)


def list_channel_settings(*, tenant_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    items = [get_channel_settings(tenant_id=tid, channel=ch) for ch in OUTBOUND_CHANNELS]
    return {"items": items, "count": len(items), "tenant_id": tid}


def upsert_channel_settings(
    *,
    tenant_id: str,
    channel: str,
    payload: dict[str, Any],
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if channel not in OUTBOUND_CHANNELS:
        raise ChannelSettingsError(f"Invalid channel '{channel}'", status_code=422)

    actor = actor or {}
    updates: dict[str, Any] = {
        "updated_at": _now(),
        "updated_by_user_id": actor.get("user_id") or actor.get("username"),
        "updated_by_username": actor.get("username") or actor.get("user_id"),
    }

    if "enabled" in payload and payload["enabled"] is not None:
        updates["enabled"] = bool(payload["enabled"])

    try:
        if channel == CHANNEL_EMAIL:
            for key in (
                "smtp_host",
                "smtp_username",
                "from_address",
            ):
                if key in payload:
                    raw = payload[key]
                    updates[key] = (str(raw).strip() or None) if raw is not None else None
            if "smtp_port" in payload and payload["smtp_port"] is not None:
                port = int(payload["smtp_port"])
                if port < 1 or port > 65535:
                    raise ChannelSettingsError("smtp_port out of range", status_code=422)
                updates["smtp_port"] = port
            if "smtp_use_tls" in payload and payload["smtp_use_tls"] is not None:
                updates["smtp_use_tls"] = bool(payload["smtp_use_tls"])
            if "smtp_password_env_ref" in payload:
                updates["smtp_password_env_ref"] = normalize_env_ref(
                    payload.get("smtp_password_env_ref")
                )
        elif channel == CHANNEL_SMS:
            for key in (
                "twilio_account_sid_env_ref",
                "twilio_auth_token_env_ref",
            ):
                if key in payload:
                    updates[key] = normalize_env_ref(payload.get(key))
            if "twilio_from_number" in payload:
                raw = payload.get("twilio_from_number")
                updates["twilio_from_number"] = (
                    (str(raw).strip() or None) if raw is not None else None
                )
        elif channel == CHANNEL_SLACK:
            for key in ("webhook_url_env_ref", "bot_token_env_ref"):
                if key in payload:
                    updates[key] = normalize_env_ref(payload.get(key))
            if "default_channel" in payload:
                raw = payload.get("default_channel")
                updates["default_channel"] = (
                    (str(raw).strip() or None) if raw is not None else None
                )
    except ProviderError as exc:
        raise ChannelSettingsError(exc.message, status_code=422) from exc
    except ChannelSettingsError:
        raise
    except Exception as exc:
        raise ChannelSettingsError(str(exc), status_code=422) from exc

    existing = _coll().find_one({"tenant_id": tid, "channel": channel})
    if existing is None:
        doc = _default_doc(tid, channel)
        doc.update(updates)
        _coll().insert_one(doc)
        return _public_view(doc, channel=channel, tenant_id=tid)

    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "channel": channel},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    return _public_view(doc, channel=channel, tenant_id=tid)


def ensure_channel_settings_indexes() -> None:
    coll = _coll()
    coll.create_index(
        [("tenant_id", ASCENDING), ("channel", ASCENDING)],
        unique=True,
        name="tenant_channel_unique",
    )
