"""CMDB component inventory API (tenant-scoped)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from pydantic import BaseModel, Field

from ...auth import require_user
from ..models.component_io import ComponentBulkUpdate
from ..models.components import COMPONENT_TYPES, ComponentCreate, ComponentUpdate
from ..models.people import PeopleLinkCreate, PeopleLinkUpdate
from ..models.work_info import WorkInfoCreate
from ...permissions import PERM_CMDB_WRITE, require_permission
from ...services import audit as audit_service
from ..services import ai_cmdb_assist as ai_cmdb_assist_service
from ..services import component_io as component_io_service
from ..services import components as components_service
from ..services import people as people_service
from ..services import work_info as work_info_service
from ..services.components import ComponentError
from ..services.people import PeopleError
from ..services.work_info import WorkInfoError
from ...tenant_context import TenantContext, require_tenant

router = APIRouter(
    prefix="/api/components",
    tags=["cmdb-components"],
    dependencies=[Depends(require_user)],
)


def _raise(exc: ComponentError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/types")
def list_component_types() -> dict[str, Any]:
    return {"types": list(COMPONENT_TYPES)}


class ClassificationSuggestRequest(BaseModel):
    """Draft CI fields for assist-only classification (C1)."""

    draft: dict[str, Any] = Field(default_factory=dict)
    force_fallback: bool = False


@router.post("/ai/suggest-classification")
def suggest_classification(
    payload: ClassificationSuggestRequest,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Suggest component_type + fields. Does not write inventory — human Apply/Save."""
    return ai_cmdb_assist_service.suggest_classification(
        payload.draft or {},
        tenant_id=tenant.tenant_id,
        force_fallback=bool(payload.force_fallback),
    )


@router.get("/filter-options")
def filter_options(
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Distinct environments / statuses / types for inventory filter controls."""
    return components_service.list_filter_options(tenant_id=tenant.tenant_id)


@router.get("/import/fields")
def import_fields() -> dict[str, Any]:
    return component_io_service.importable_field_catalog()


@router.get("/import/template")
def import_template(
    format: str = Query(default="csv", pattern="^(?i)(csv|xlsx)$"),
    _tenant: TenantContext = Depends(require_tenant),
) -> Response:
    fmt = format.lower()
    body = component_io_service.render_template(fmt)
    if fmt == "xlsx":
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "svrmon24-inventory-template.xlsx"
    else:
        media = "text/csv; charset=utf-8"
        filename = "svrmon24-inventory-template.csv"
    return Response(
        content=body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/import")
async def import_components(
    file: UploadFile = File(...),
    mapping: str | None = Form(default=None),
    dry_run: bool = Query(default=True),
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    """Validate (and optionally create) components from CSV or Excel."""
    try:
        content = await file.read()
        mapping_obj = component_io_service.parse_mapping_json(mapping)
        report = component_io_service.run_import(
            tenant_id=tenant.tenant_id,
            filename=file.filename or "upload",
            content=content,
            content_type=file.content_type,
            mapping=mapping_obj,
            dry_run=dry_run,
        )
    except ComponentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    if not dry_run and report.created:
        audit_service.record_from_tenant(
            tenant,
            action="component.import",
            resource_type="component",
            resource_id=None,
            details={
                "filename": report.filename,
                "format": report.format,
                "created": report.created,
                "invalid_rows": report.invalid_rows,
                "total_rows": report.total_rows,
            },
            request_method="POST",
            request_path="/api/components/import",
        )
    return report.model_dump()


@router.get("/export")
def export_components(
    format: str = Query(default="csv", pattern="^(?i)(csv|xlsx)$"),
    q: str | None = Query(default=None, description="Search text"),
    component_type: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    status: str | None = Query(default=None),
    os_family: str | None = Query(default=None),
    product_type: str | None = Query(default=None),
    tenant: TenantContext = Depends(require_tenant),
) -> Response:
    """Export the current filtered inventory as CSV or Excel."""
    if component_type and component_type not in COMPONENT_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid component_type: {component_type}")
    fmt = format.lower()
    items = component_io_service.build_export_rows(
        tenant_id=tenant.tenant_id,
        q=q,
        component_type=component_type,
        environment=environment,
        status=status,
        os_family=os_family,
        product_type=product_type,
    )
    if fmt == "xlsx":
        body = component_io_service.render_xlsx(items)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "svrmon24-inventory.xlsx"
    else:
        body = component_io_service.render_csv(items)
        media = "text/csv; charset=utf-8"
        filename = "svrmon24-inventory.csv"
    return Response(
        content=body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Count": str(len(items)),
            "X-Export-Format": fmt,
            "Access-Control-Expose-Headers": "Content-Disposition, X-Export-Count, X-Export-Format",
        },
    )


@router.post("/bulk-update")
def bulk_update_components(
    payload: ComponentBulkUpdate,
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    """Batch-update status and/or environment on selected components."""
    try:
        result = components_service.bulk_update_components(
            tenant_id=tenant.tenant_id,
            component_ids=payload.component_ids,
            status=payload.status.value if payload.status is not None else None,
            environment=payload.environment,
        )
    except ComponentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="component.bulk_update",
        resource_type="component",
        resource_id=None,
        details={
            "requested": result.get("requested"),
            "updated": result.get("updated"),
            "fields": result.get("fields"),
        },
        request_method="POST",
        request_path="/api/components/bulk-update",
    )
    return result


@router.get("")
def list_components(
    q: str | None = Query(default=None, description="Search text"),
    component_type: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    status: str | None = Query(default=None),
    os_family: str | None = Query(default=None),
    product_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc", pattern="^(?i)(asc|desc)$"),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    if component_type and component_type not in COMPONENT_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid component_type: {component_type}")
    return components_service.list_components(
        tenant_id=tenant.tenant_id,
        q=q,
        component_type=component_type,
        environment=environment,
        status=status,
        os_family=os_family,
        product_type=product_type,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.post("", status_code=201)
def create_component(
    payload: ComponentCreate,
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    try:
        doc = components_service.create_component(payload, tenant_id=tenant.tenant_id)
    except ComponentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    except Exception as exc:
        from ..services.custom_fields import CustomFieldError

        if isinstance(exc, CustomFieldError):
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        raise
    audit_service.record_from_tenant(
        tenant,
        action="component.create",
        resource_type="component",
        resource_id=doc.get("component_id"),
        details={
            "component_type": doc.get("component_type"),
            "name": doc.get("name"),
        },
        request_method="POST",
        request_path="/api/components",
    )
    return doc


@router.get("/{component_id}")
def get_component(
    component_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    doc = components_service.get_component(component_id, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Component '{component_id}' not found")
    return doc


@router.put("/{component_id}")
def update_component(
    component_id: str,
    payload: ComponentUpdate,
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    try:
        doc = components_service.update_component(
            component_id, payload, tenant_id=tenant.tenant_id
        )
    except ComponentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    except Exception as exc:
        from ..services.custom_fields import CustomFieldError

        if isinstance(exc, CustomFieldError):
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        raise
    audit_service.record_from_tenant(
        tenant,
        action="component.update",
        resource_type="component",
        resource_id=component_id,
        details={"component_type": doc.get("component_type")},
        request_method="PUT",
        request_path=f"/api/components/{component_id}",
    )
    return doc


@router.get("/{component_id}/relationship-details")
def get_relationship_details(
    component_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Helix Relationship Details projection — tree + grouped child CIs (C2)."""
    from ..services import relationships as relationships_service
    from ..services.relationships import RelationshipError

    try:
        return relationships_service.relationship_details(
            component_id, tenant_id=tenant.tenant_id
        )
    except RelationshipError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{component_id}/delete-preview")
def delete_preview(
    component_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    try:
        return components_service.delete_preview(
            component_id, tenant_id=tenant.tenant_id
        )
    except ComponentError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.delete("/{component_id}")
def delete_component(
    component_id: str,
    confirmed: bool = Query(default=False, description="Must be true to delete"),
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    try:
        result = components_service.delete_component(
            component_id, confirmed=confirmed, tenant_id=tenant.tenant_id
        )
    except ComponentError as exc:
        _raise(exc)
        raise  # pragma: no cover
    if confirmed:
        audit_service.record_from_tenant(
            tenant,
            action="component.delete",
            resource_type="component",
            resource_id=component_id,
            request_method="DELETE",
            request_path=f"/api/components/{component_id}",
        )
    return result


# ---------------------------------------------------------------------------
# C3 — People + Work Info (Helix CI detail tabs)
# ---------------------------------------------------------------------------


def _raise_people(exc: PeopleError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _raise_work_info(exc: WorkInfoError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{component_id}/people")
def list_people(
    component_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return people_service.list_people(
            component_id, tenant_id=tenant.tenant_id
        )
    except PeopleError as exc:
        _raise_people(exc)
        raise  # pragma: no cover


@router.get("/{component_id}/people/primary")
def get_primary_people_contact(
    component_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Primary contact for ITSM assignment hints (API-only; no cross-DB joins)."""
    try:
        # 404 if CI missing / wrong tenant.
        people_service.list_people(component_id, tenant_id=tenant.tenant_id)
    except PeopleError as exc:
        _raise_people(exc)
        raise  # pragma: no cover
    primary = people_service.get_primary_contact(
        component_id, tenant_id=tenant.tenant_id
    )
    hint = None
    if primary:
        if primary.get("party_type") == "support_group":
            hint = {
                "assignment_group": primary.get("display_name")
                or primary.get("party_id"),
                "party_type": primary.get("party_type"),
                "party_id": primary.get("party_id"),
                "role": primary.get("role"),
            }
        else:
            hint = {
                "assignee_hint": primary.get("display_name")
                or primary.get("party_id"),
                "party_type": primary.get("party_type"),
                "party_id": primary.get("party_id"),
                "role": primary.get("role"),
            }
    return {
        "component_id": component_id,
        "tenant_id": tenant.tenant_id,
        "primary": primary,
        "assignment_hint": hint,
    }


@router.post("/{component_id}/people", status_code=201)
def create_people_link(
    component_id: str,
    payload: PeopleLinkCreate,
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    try:
        doc = people_service.create_people_link(
            component_id, payload, tenant_id=tenant.tenant_id
        )
    except PeopleError as exc:
        _raise_people(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="component.people.create",
        resource_type="cmdb_ci_people",
        resource_id=doc.get("link_id"),
        details={"component_id": component_id, "role": doc.get("role")},
        request_method="POST",
        request_path=f"/api/components/{component_id}/people",
    )
    return doc


@router.patch("/{component_id}/people/{link_id}")
def update_people_link(
    component_id: str,
    link_id: str,
    payload: PeopleLinkUpdate,
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    try:
        doc = people_service.update_people_link(
            component_id, link_id, payload, tenant_id=tenant.tenant_id
        )
    except PeopleError as exc:
        _raise_people(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="component.people.update",
        resource_type="cmdb_ci_people",
        resource_id=link_id,
        details={"component_id": component_id},
        request_method="PATCH",
        request_path=f"/api/components/{component_id}/people/{link_id}",
    )
    return doc


@router.delete("/{component_id}/people/{link_id}")
def delete_people_link(
    component_id: str,
    link_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    try:
        result = people_service.delete_people_link(
            component_id, link_id, tenant_id=tenant.tenant_id
        )
    except PeopleError as exc:
        _raise_people(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="component.people.delete",
        resource_type="cmdb_ci_people",
        resource_id=link_id,
        details={"component_id": component_id},
        request_method="DELETE",
        request_path=f"/api/components/{component_id}/people/{link_id}",
    )
    return result


@router.get("/{component_id}/work-info")
def list_work_info(
    component_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return work_info_service.list_work_info(
            component_id, tenant_id=tenant.tenant_id
        )
    except WorkInfoError as exc:
        _raise_work_info(exc)
        raise  # pragma: no cover


@router.post("/{component_id}/work-info", status_code=201)
def create_work_info(
    component_id: str,
    payload: WorkInfoCreate,
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    try:
        doc = work_info_service.create_work_info(
            component_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=audit_service.actor_from_tenant(tenant),
        )
    except WorkInfoError as exc:
        _raise_work_info(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="component.work_info.create",
        resource_type="cmdb_ci_work_info",
        resource_id=doc.get("work_info_id"),
        details={"component_id": component_id, "summary": doc.get("summary")},
        request_method="POST",
        request_path=f"/api/components/{component_id}/work-info",
    )
    return doc


@router.get("/{component_id}/work-info/{work_info_id}")
def get_work_info(
    component_id: str,
    work_info_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    try:
        return work_info_service.get_work_info(
            component_id, work_info_id, tenant_id=tenant.tenant_id
        )
    except WorkInfoError as exc:
        _raise_work_info(exc)
        raise  # pragma: no cover


@router.delete("/{component_id}/work-info/{work_info_id}")
def delete_work_info(
    component_id: str,
    work_info_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    try:
        result = work_info_service.delete_work_info(
            component_id, work_info_id, tenant_id=tenant.tenant_id
        )
    except WorkInfoError as exc:
        _raise_work_info(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="component.work_info.delete",
        resource_type="cmdb_ci_work_info",
        resource_id=work_info_id,
        details={"component_id": component_id},
        request_method="DELETE",
        request_path=f"/api/components/{component_id}/work-info/{work_info_id}",
    )
    return result


@router.post(
    "/{component_id}/work-info/{work_info_id}/attachments",
    status_code=201,
)
async def upload_work_info_attachment(
    component_id: str,
    work_info_id: str,
    file: UploadFile = File(...),
    content_type: str | None = Form(default=None),
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    raw = await file.read()
    try:
        doc = work_info_service.add_attachment(
            component_id,
            work_info_id,
            tenant_id=tenant.tenant_id,
            filename=file.filename or "attachment.bin",
            content=raw,
            content_type=content_type or file.content_type,
            actor=audit_service.actor_from_tenant(tenant),
        )
    except WorkInfoError as exc:
        _raise_work_info(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="component.work_info.attachment",
        resource_type="cmdb_ci_attachments",
        resource_id=doc.get("attachment_id"),
        details={
            "component_id": component_id,
            "work_info_id": work_info_id,
            "filename": doc.get("filename"),
        },
        request_method="POST",
        request_path=(
            f"/api/components/{component_id}/work-info/{work_info_id}/attachments"
        ),
    )
    return doc


@router.get(
    "/{component_id}/work-info/{work_info_id}/attachments/{attachment_id}/content"
)
def download_work_info_attachment(
    component_id: str,
    work_info_id: str,
    attachment_id: str,
    tenant: TenantContext = Depends(require_tenant),
) -> Response:
    try:
        meta, data = work_info_service.download_attachment(
            component_id,
            work_info_id,
            attachment_id,
            tenant_id=tenant.tenant_id,
        )
    except WorkInfoError as exc:
        _raise_work_info(exc)
        raise  # pragma: no cover
    filename = str(meta.get("filename") or "attachment.bin")
    media = str(meta.get("content_type") or "application/octet-stream")
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.delete(
    "/{component_id}/work-info/{work_info_id}/attachments/{attachment_id}"
)
def delete_work_info_attachment(
    component_id: str,
    work_info_id: str,
    attachment_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_CMDB_WRITE)),
) -> dict[str, Any]:
    try:
        return work_info_service.delete_attachment(
            component_id,
            work_info_id,
            attachment_id,
            tenant_id=tenant.tenant_id,
        )
    except WorkInfoError as exc:
        _raise_work_info(exc)
        raise  # pragma: no cover
