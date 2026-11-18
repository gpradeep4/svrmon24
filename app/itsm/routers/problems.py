"""Problem Management APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...permissions import PERM_ITSM_PROBLEM_READ, PERM_ITSM_PROBLEM_WRITE, require_permission
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..models.problems import (
    ProblemCiLinkCreate,
    ProblemCreate,
    ProblemTransition,
    ProblemUpdate,
)
from ..services import problems as problems_service
from ..services.problems import ProblemError

router = APIRouter(prefix="/problems", tags=["itsm-problems"])


def _raise(exc: ProblemError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


@router.get("")
def list_problems(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    assignee_user_id: str | None = Query(default=None),
    component_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_PROBLEM_READ)),
) -> dict[str, Any]:
    try:
        return problems_service.list_problems(
            tenant_id=tenant.tenant_id,
            q=q,
            status=status,
            priority=priority,
            assignee_user_id=assignee_user_id,
            component_id=component_id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except ProblemError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("", status_code=201)
def create_problem(
    payload: ProblemCreate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_PROBLEM_WRITE)),
) -> dict[str, Any]:
    try:
        doc = problems_service.create_problem(
            payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except ProblemError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.problem.create",
        resource_type="itsm_problem",
        resource_id=doc.get("problem_id"),
        details={"number": doc.get("number"), "status": doc.get("status")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/{problem_id}")
def get_problem(
    problem_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_PROBLEM_READ)),
) -> dict[str, Any]:
    doc = problems_service.get_problem(problem_id, tenant_id=tenant.tenant_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Problem '{problem_id}' not found"
        )
    return doc


@router.patch("/{problem_id}")
def update_problem(
    problem_id: str,
    payload: ProblemUpdate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_PROBLEM_WRITE)),
) -> dict[str, Any]:
    try:
        doc = problems_service.update_problem(
            problem_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except ProblemError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.problem.update",
        resource_type="itsm_problem",
        resource_id=problem_id,
        details=payload.model_dump(exclude_unset=True),
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/{problem_id}/transition")
def transition_problem(
    problem_id: str,
    payload: ProblemTransition,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_PROBLEM_WRITE)),
) -> dict[str, Any]:
    try:
        doc = problems_service.transition_problem(
            problem_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except ProblemError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.problem.transition",
        resource_type="itsm_problem",
        resource_id=problem_id,
        details={"status": payload.status},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/{problem_id}/ci-links", status_code=201)
def add_ci_link(
    problem_id: str,
    payload: ProblemCiLinkCreate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_PROBLEM_WRITE)),
) -> dict[str, Any]:
    try:
        doc = problems_service.add_ci_link(
            problem_id,
            component_id=payload.component_id,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except ProblemError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.problem.ci_link_add",
        resource_type="itsm_problem",
        resource_id=problem_id,
        details={"component_id": payload.component_id},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.delete("/{problem_id}/ci-links/{component_id}")
def remove_ci_link(
    problem_id: str,
    component_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_PROBLEM_WRITE)),
) -> dict[str, Any]:
    try:
        doc = problems_service.remove_ci_link(
            problem_id,
            component_id=component_id,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except ProblemError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.problem.ci_link_remove",
        resource_type="itsm_problem",
        resource_id=problem_id,
        details={"component_id": component_id},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc
