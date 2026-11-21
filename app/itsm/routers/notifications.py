"""ITSM in-app notification inbox + outbound channel admin APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...permissions import (
    PERM_ITSM_NOTIFICATION_ADMIN,
    PERM_ITSM_NOTIFICATION_READ,
    require_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..models.notifications import (
    CHANNEL_EMAIL,
    CHANNEL_SLACK,
    CHANNEL_SMS,
    EmailChannelSettingsUpdate,
    NotificationStatusUpdate,
    SlackChannelSettingsUpdate,
    SmsChannelSettingsUpdate,
)
from ..services import notification_channels as channel_settings_service
from ..services import notification_delivery as delivery_service
from ..services import notifications as notifications_service
from ..services.notification_channels import ChannelSettingsError
from ..services.notifications import NotificationError

router = APIRouter(prefix="/notifications", tags=["itsm-notifications"])


def _raise(exc: NotificationError | ChannelSettingsError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _recipient_keys(tenant: TenantContext) -> list[str]:
    return notifications_service.recipient_keys_for_user(
        user_id=tenant.user_id,
        username=tenant.auth_user.username if tenant.auth_user else None,
    )


def _actor(tenant: TenantContext) -> dict[str, str | None]:
    return {
        "user_id": tenant.user_id,
        "username": tenant.auth_user.username if tenant.auth_user else tenant.user_id,
    }


@router.get("/channels")
def list_channels(
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_NOTIFICATION_ADMIN)),
) -> dict[str, Any]:
    return channel_settings_service.list_channel_settings(tenant_id=tenant.tenant_id)


@router.get("/channels/{channel}")
def get_channel(
    channel: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_NOTIFICATION_ADMIN)),
) -> dict[str, Any]:
    try:
        return channel_settings_service.get_channel_settings(
            tenant_id=tenant.tenant_id, channel=channel
        )
    except ChannelSettingsError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.put("/channels/email")
def put_email_channel(
    payload: EmailChannelSettingsUpdate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_NOTIFICATION_ADMIN)),
) -> dict[str, Any]:
    return _upsert_channel(
        CHANNEL_EMAIL,
        payload.model_dump(exclude_unset=True),
        request=request,
        tenant=tenant,
    )


@router.put("/channels/sms")
def put_sms_channel(
    payload: SmsChannelSettingsUpdate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_NOTIFICATION_ADMIN)),
) -> dict[str, Any]:
    return _upsert_channel(
        CHANNEL_SMS,
        payload.model_dump(exclude_unset=True),
        request=request,
        tenant=tenant,
    )


@router.put("/channels/slack")
def put_slack_channel(
    payload: SlackChannelSettingsUpdate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_NOTIFICATION_ADMIN)),
) -> dict[str, Any]:
    return _upsert_channel(
        CHANNEL_SLACK,
        payload.model_dump(exclude_unset=True),
        request=request,
        tenant=tenant,
    )


def _upsert_channel(
    channel: str,
    payload: dict[str, Any],
    *,
    request: Request,
    tenant: TenantContext,
) -> dict[str, Any]:
    try:
        doc = channel_settings_service.upsert_channel_settings(
            tenant_id=tenant.tenant_id,
            channel=channel,
            payload=payload,
            actor=_actor(tenant),
        )
    except ChannelSettingsError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action=f"itsm.notification.channel.{channel}.upsert",
        resource_type="itsm_notification_channel_settings",
        resource_id=channel,
        details={"enabled": doc.get("enabled"), "channel": channel},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/deliveries")
def list_deliveries(
    channel: str | None = Query(default=None),
    status: str | None = Query(default=None),
    notification_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_NOTIFICATION_ADMIN)),
) -> dict[str, Any]:
    return delivery_service.list_deliveries(
        tenant_id=tenant.tenant_id,
        channel=channel,
        status=status,
        notification_id=notification_id,
        page=page,
        page_size=page_size,
    )


@router.get("")
def list_notifications(
    status: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_NOTIFICATION_READ)),
) -> dict[str, Any]:
    try:
        return notifications_service.list_inbox(
            tenant_id=tenant.tenant_id,
            recipient_keys=_recipient_keys(tenant),
            status=status,
            event_type=event_type,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
            include_archived=include_archived,
        )
    except NotificationError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/unread-count")
def get_unread_count(
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_NOTIFICATION_READ)),
) -> dict[str, Any]:
    return notifications_service.unread_count(
        tenant_id=tenant.tenant_id,
        recipient_keys=_recipient_keys(tenant),
    )


@router.get("/{notification_id}")
def get_notification(
    notification_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_NOTIFICATION_READ)),
) -> dict[str, Any]:
    doc = notifications_service.get_notification(
        notification_id,
        tenant_id=tenant.tenant_id,
        recipient_keys=_recipient_keys(tenant),
    )
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Notification '{notification_id}' not found",
        )
    return doc


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_NOTIFICATION_READ)),
) -> dict[str, Any]:
    return _set_status(notification_id, status="read", request=request, tenant=tenant)


@router.post("/{notification_id}/unread")
def mark_unread(
    notification_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_NOTIFICATION_READ)),
) -> dict[str, Any]:
    return _set_status(notification_id, status="unread", request=request, tenant=tenant)


@router.post("/{notification_id}/archive")
def mark_archive(
    notification_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_NOTIFICATION_READ)),
) -> dict[str, Any]:
    return _set_status(
        notification_id, status="archived", request=request, tenant=tenant
    )


@router.patch("/{notification_id}")
def patch_status(
    notification_id: str,
    payload: NotificationStatusUpdate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_NOTIFICATION_READ)),
) -> dict[str, Any]:
    return _set_status(
        notification_id, status=payload.status, request=request, tenant=tenant
    )


def _set_status(
    notification_id: str,
    *,
    status: str,
    request: Request,
    tenant: TenantContext,
) -> dict[str, Any]:
    try:
        doc = notifications_service.set_status(
            notification_id,
            tenant_id=tenant.tenant_id,
            recipient_keys=_recipient_keys(tenant),
            status=status,
        )
    except NotificationError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action=f"itsm.notification.{status}",
        resource_type="itsm_notification",
        resource_id=notification_id,
        details={"status": status},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc
