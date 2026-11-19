"""ITSM in-app notification inbox APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...permissions import PERM_ITSM_NOTIFICATION_READ, require_permission
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..models.notifications import NotificationStatusUpdate
from ..services import notifications as notifications_service
from ..services.notifications import NotificationError

router = APIRouter(prefix="/notifications", tags=["itsm-notifications"])


def _raise(exc: NotificationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _recipient_keys(tenant: TenantContext) -> list[str]:
    return notifications_service.recipient_keys_for_user(
        user_id=tenant.user_id,
        username=tenant.auth_user.username if tenant.auth_user else None,
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
