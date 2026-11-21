"""CMDB component inventory API (tenant-scoped)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from ...auth import require_user
from ..models.component_io import ComponentBulkUpdate
from ..models.components import COMPONENT_TYPES, ComponentCreate, ComponentUpdate
from ...permissions import PERM_CMDB_WRITE, require_permission
from ...services import audit as audit_service
from ..services import component_io as component_io_service
from ..services import components as components_service
from ..services.components import ComponentError
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
