"""In-app notification request / status models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NOTIFICATION_CHANNELS: tuple[str, ...] = ("in_app", "email", "sms", "slack")
NOTIFICATION_STATUSES: tuple[str, ...] = ("unread", "read", "archived")
NOTIFICATION_EVENT_TYPES: tuple[str, ...] = (
    "assignment",
    "status_change",
    "approval_requested",
    "approval_decided",
    "sla_breach",
)

# Implemented channel for this slice; others are design hooks only.
CHANNEL_IN_APP = "in_app"

NotificationChannel = Literal["in_app", "email", "sms", "slack"]
NotificationStatus = Literal["unread", "read", "archived"]
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
