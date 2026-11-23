"""Service Portal execution APIs (SIMULATED first)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...permissions import (
    PERM_SP_ADMIN,
    PERM_SP_EXECUTION_READ,
    PERM_SP_EXECUTION_RUN,
    assert_any_permission,
    require_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext, require_tenant
from ..models.executions import ExecutionRequeue, SimulateTickBody
from ..services import execution as execution_service
from ..services.execution import ExecutionError

router = APIRouter(tags=["portal-executions"])


def _raise(exc: ExecutionError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


def _require_exec_run(
    tenant: TenantContext = Depends(require_tenant),
) -> TenantContext:
    assert_any_permission(tenant, (PERM_SP_EXECUTION_RUN, PERM_SP_ADMIN))
    return tenant


@router.get("/executions")
def list_executions(
    status: str | None = Query(default=None),
    request_id: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_SP_EXECUTION_READ)),
) -> dict[str, Any]:
    try:
        return execution_service.list_runs(
            tenant_id=tenant.tenant_id,
            status=status,
            request_id=request_id,
            domain=domain,
            page=page,
            page_size=page_size,
        )
    except ExecutionError as exc:
        _raise(exc)
    return {}


@router.get("/executions/{run_id}")
def get_execution(
    run_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_SP_EXECUTION_READ)),
) -> dict[str, Any]:
    try:
        return execution_service.get_run(
            tenant_id=tenant.tenant_id, run_id=run_id
        )
    except ExecutionError as exc:
        _raise(exc)
    return {}


@router.post("/executions/{request_id}/requeue")
def requeue_execution(
    request_id: str,
    payload: ExecutionRequeue | None = None,
    tenant: TenantContext = Depends(_require_exec_run),
) -> dict[str, Any]:
    body = payload or ExecutionRequeue()
    try:
        run = execution_service.requeue_request(
            request_id,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
            dry_run=body.dry_run,
            collect_mode=body.collect_mode,
        )
    except ExecutionError as exc:
        _raise(exc)
        return {}
    audit_service.record_event(
        tenant_id=tenant.tenant_id,
        action="portal.execution.requeue",
        resource_type="sp_execution_run",
        resource_id=run.get("run_id"),
        actor=_actor(tenant),
        details={"request_id": request_id},
    )
    return run


@router.post("/admin/simulate-tick")
def simulate_tick(
    payload: SimulateTickBody | None = None,
    tenant: TenantContext = Depends(_require_exec_run),
) -> dict[str, Any]:
    body = payload or SimulateTickBody()
    try:
        result = execution_service.simulate_tick(
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
            limit=body.limit,
        )
    except ExecutionError as exc:
        _raise(exc)
        return {}
    audit_service.record_event(
        tenant_id=tenant.tenant_id,
        action="portal.execution.simulate_tick",
        resource_type="sp_execution_run",
        resource_id="tick",
        actor=_actor(tenant),
        details={"advanced": result.get("advanced")},
    )
    return result
