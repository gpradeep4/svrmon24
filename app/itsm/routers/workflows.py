"""Workflow definition and execution APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...permissions import (
    PERM_ITSM_WORKFLOW_ADMIN,
    PERM_ITSM_WORKFLOW_READ,
    require_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..models.workflows import (
    WorkflowActivate,
    WorkflowAdvance,
    WorkflowCreate,
    WorkflowStartExecution,
    WorkflowUpdate,
)
from ..services import workflow_engine as engine_service
from ..services import workflows as workflows_service
from ..services.approvals import ApprovalError
from ..services.workflow_engine import ExecutionError
from ..services.workflows import WorkflowError

router = APIRouter(tags=["itsm-workflows"])


def _raise_wf(exc: WorkflowError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _raise_ex(exc: ExecutionError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


# --- Definitions -----------------------------------------------------------------


@router.get("/workflows")
def list_workflows(
    q: str | None = Query(default=None),
    applies_to: str | None = Query(default=None),
    active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_WORKFLOW_READ)),
) -> dict[str, Any]:
    try:
        return workflows_service.list_workflows(
            tenant_id=tenant.tenant_id,
            q=q,
            applies_to=applies_to,
            active=active,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except WorkflowError as exc:
        _raise_wf(exc)
        raise  # pragma: no cover


@router.post("/workflows", status_code=201)
def create_workflow(
    payload: WorkflowCreate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_WORKFLOW_ADMIN)),
) -> dict[str, Any]:
    try:
        doc = workflows_service.create_workflow(
            payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except WorkflowError as exc:
        _raise_wf(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.workflow.create",
        resource_type="itsm_workflow",
        resource_id=doc.get("workflow_id"),
        details={"name": doc.get("name"), "version": doc.get("version")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/workflows/{workflow_id}")
def get_workflow(
    workflow_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_WORKFLOW_READ)),
) -> dict[str, Any]:
    doc = workflows_service.get_workflow(workflow_id, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Workflow '{workflow_id}' not found"
        )
    return doc


@router.patch("/workflows/{workflow_id}")
def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_WORKFLOW_ADMIN)),
) -> dict[str, Any]:
    try:
        doc = workflows_service.update_workflow(
            workflow_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except WorkflowError as exc:
        _raise_wf(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.workflow.update",
        resource_type="itsm_workflow",
        resource_id=workflow_id,
        details={"version": doc.get("version")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/workflows/{workflow_id}/activate")
def activate_workflow(
    workflow_id: str,
    payload: WorkflowActivate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_WORKFLOW_ADMIN)),
) -> dict[str, Any]:
    try:
        doc = workflows_service.set_workflow_active(
            workflow_id,
            active=payload.active,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except WorkflowError as exc:
        _raise_wf(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.workflow.activate",
        resource_type="itsm_workflow",
        resource_id=workflow_id,
        details={"active": payload.active},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/workflows/{workflow_id}/publish")
def publish_workflow(
    workflow_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_WORKFLOW_ADMIN)),
) -> dict[str, Any]:
    try:
        doc = workflows_service.publish_workflow(
            workflow_id, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except WorkflowError as exc:
        _raise_wf(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.workflow.publish",
        resource_type="itsm_workflow",
        resource_id=workflow_id,
        details={"active": True, "version": doc.get("version")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/workflows/{workflow_id}/start", status_code=201)
def start_workflow_execution(
    workflow_id: str,
    payload: WorkflowStartExecution,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_WORKFLOW_ADMIN)),
) -> dict[str, Any]:
    try:
        doc = engine_service.start_execution(
            workflow_id,
            ticket_type=payload.ticket_type,
            ticket_id=payload.ticket_id,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
            context=payload.context,
        )
    except ExecutionError as exc:
        _raise_ex(exc)
        raise  # pragma: no cover
    except ApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    audit_service.record_from_tenant(
        tenant,
        action="itsm.workflow_execution.start",
        resource_type="itsm_workflow_execution",
        resource_id=doc.get("execution_id"),
        details={
            "workflow_id": workflow_id,
            "ticket_type": payload.ticket_type,
            "ticket_id": payload.ticket_id,
            "status": doc.get("status"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


# --- Executions ------------------------------------------------------------------


@router.get("/workflow-executions")
def list_executions(
    workflow_id: str | None = Query(default=None),
    ticket_type: str | None = Query(default=None),
    ticket_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_WORKFLOW_READ)),
) -> dict[str, Any]:
    try:
        return engine_service.list_executions(
            tenant_id=tenant.tenant_id,
            workflow_id=workflow_id,
            ticket_type=ticket_type,
            ticket_id=ticket_id,
            status=status,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except ExecutionError as exc:
        _raise_ex(exc)
        raise  # pragma: no cover


@router.get("/workflow-executions/{execution_id}")
def get_execution(
    execution_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_WORKFLOW_READ)),
) -> dict[str, Any]:
    doc = engine_service.get_execution(execution_id, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Execution '{execution_id}' not found"
        )
    return doc


@router.post("/workflow-executions/{execution_id}/advance")
def advance_execution(
    execution_id: str,
    payload: WorkflowAdvance,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_WORKFLOW_ADMIN)),
) -> dict[str, Any]:
    try:
        doc = engine_service.advance_execution(
            execution_id,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
            branch=payload.branch,
            comment=payload.comment,
        )
    except ExecutionError as exc:
        _raise_ex(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.workflow_execution.advance",
        resource_type="itsm_workflow_execution",
        resource_id=execution_id,
        details={"status": doc.get("status"), "branch": payload.branch},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/workflow-executions/{execution_id}/cancel")
def cancel_execution(
    execution_id: str,
    payload: WorkflowAdvance,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_WORKFLOW_ADMIN)),
) -> dict[str, Any]:
    try:
        doc = engine_service.cancel_execution(
            execution_id,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
            comment=payload.comment,
        )
    except ExecutionError as exc:
        _raise_ex(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.workflow_execution.cancel",
        resource_type="itsm_workflow_execution",
        resource_id=execution_id,
        details={"comment": payload.comment},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc
