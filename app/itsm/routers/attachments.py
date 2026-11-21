"""Ticket attachment APIs — multipart upload, tenant-scoped download."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from ...permissions import (
    PERM_ITSM_CHANGE_READ,
    PERM_ITSM_CHANGE_WRITE,
    PERM_ITSM_INCIDENT_READ,
    PERM_ITSM_INCIDENT_WRITE,
    PERM_ITSM_PROBLEM_READ,
    PERM_ITSM_PROBLEM_WRITE,
    has_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext, require_tenant
from ..services import attachments as attachments_service
from ..services.attachments import AttachmentError

router = APIRouter(tags=["itsm-attachments"])

_READ_PERMS = {
    "incident": PERM_ITSM_INCIDENT_READ,
    "change": PERM_ITSM_CHANGE_READ,
    "problem": PERM_ITSM_PROBLEM_READ,
}
_WRITE_PERMS = {
    "incident": PERM_ITSM_INCIDENT_WRITE,
    "change": PERM_ITSM_CHANGE_WRITE,
    "problem": PERM_ITSM_PROBLEM_WRITE,
}


def _raise(exc: AttachmentError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


def _require_ticket_perm(tenant: TenantContext, ticket_type: str, *, write: bool) -> None:
    ttype = (ticket_type or "").strip().lower()
    table = _WRITE_PERMS if write else _READ_PERMS
    perm = table.get(ttype)
    if perm is None:
        raise HTTPException(status_code=400, detail=f"Invalid ticket_type '{ticket_type}'")
    if not has_permission(tenant, perm):
        raise HTTPException(status_code=403, detail=f"Missing permission {perm}")


@router.get("/{ticket_type}/{ticket_id}/attachments")
def list_ticket_attachments(
    ticket_type: str,
    ticket_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    _require_ticket_perm(tenant, ticket_type, write=False)
    try:
        return attachments_service.list_attachments(
            tenant_id=tenant.tenant_id,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
        )
    except AttachmentError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/{ticket_type}/{ticket_id}/attachments", status_code=201)
async def upload_ticket_attachment(
    ticket_type: str,
    ticket_id: str,
    file: UploadFile = File(...),
    content_type: str | None = Form(default=None),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    _require_ticket_perm(tenant, ticket_type, write=True)
    raw = await file.read()
    try:
        return attachments_service.create_attachment(
            tenant_id=tenant.tenant_id,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            filename=file.filename or "attachment.bin",
            content=raw,
            content_type=content_type or file.content_type,
            actor=_actor(tenant),
        )
    except AttachmentError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/attachments/{attachment_id}")
def get_attachment_meta(
    attachment_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    doc = attachments_service.get_attachment_meta(
        attachment_id, tenant_id=tenant.tenant_id
    )
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Attachment '{attachment_id}' not found"
        )
    _require_ticket_perm(tenant, str(doc.get("ticket_type") or ""), write=False)
    return doc


@router.get("/attachments/{attachment_id}/content")
def download_attachment_content(
    attachment_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> Response:
    try:
        meta, data = attachments_service.download_attachment(
            attachment_id, tenant_id=tenant.tenant_id
        )
    except AttachmentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    _require_ticket_perm(tenant, str(meta.get("ticket_type") or ""), write=False)
    filename = str(meta.get("filename") or "attachment.bin")
    media = str(meta.get("content_type") or "application/octet-stream")
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Tenant-Id": tenant.tenant_id,
        },
    )


@router.delete("/attachments/{attachment_id}")
def delete_attachment(
    attachment_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    meta = attachments_service.get_attachment_meta(
        attachment_id, tenant_id=tenant.tenant_id
    )
    if meta is None:
        raise HTTPException(
            status_code=404, detail=f"Attachment '{attachment_id}' not found"
        )
    _require_ticket_perm(tenant, str(meta.get("ticket_type") or ""), write=True)
    try:
        return attachments_service.delete_attachment(
            attachment_id, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except AttachmentError as exc:
        _raise(exc)
        raise  # pragma: no cover
