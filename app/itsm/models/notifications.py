"""In-app notification + outbound channel settings models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NOTIFICATION_CHANNELS: tuple[str, ...] = ("in_app", "email", "sms", "slack")
OUTBOUND_CHANNELS: tuple[str, ...] = ("email", "sms", "slack")
NOTIFICATION_STATUSES: tuple[str, ...] = ("unread", "read", "archived")
DELIVERY_STATUSES: tuple[str, ...] = (
    "pending",
    "sent",
    "failed",
    "skipped",
    "denied",
)
NOTIFICATION_EVENT_TYPES: tuple[str, ...] = (
    "assignment",
    "status_change",
    "approval_requested",
    "approval_decided",
    "sla_breach",
)

CHANNEL_IN_APP = "in_app"
CHANNEL_EMAIL = "email"
CHANNEL_SMS = "sms"
CHANNEL_SLACK = "slack"

NotificationChannel = Literal["in_app", "email", "sms", "slack"]
OutboundChannel = Literal["email", "sms", "slack"]
NotificationStatus = Literal["unread", "read", "archived"]
DeliveryStatus = Literal["pending", "sent", "failed", "skipped", "denied"]
NotificationEventType = Literal[
    "assignment",
    "status_change",
    "approval_requested",
    "approval_decided",
    "sla_breach",
]


class NotificationStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: NotificationStatus


class EmailChannelSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_use_tls: bool | None = None
    smtp_username: str | None = None
    smtp_password_env_ref: str | None = Field(
        default=None,
        description="Env var name holding the SMTP password (never the secret)",
    )
    from_address: str | None = None


class SmsChannelSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    twilio_account_sid_env_ref: str | None = None
    twilio_auth_token_env_ref: str | None = None
    twilio_from_number: str | None = None


class SlackChannelSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    webhook_url_env_ref: str | None = None
    bot_token_env_ref: str | None = None
    default_channel: str | None = None
