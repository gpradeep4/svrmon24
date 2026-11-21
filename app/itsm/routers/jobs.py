"""ITSM background job status + forced tick APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ...config import Settings, get_settings
from ...permissions import PERM_ITSM_JOBS_ADMIN, require_permission
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..services import job_runner
from ..services import jobs as jobs_service
from ..services.jobs import ALL_JOBS, JobError

router = APIRouter(prefix="/jobs", tags=["itsm-jobs"])


class JobTickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: list[str] | None = Field(
        default=None,
        description="Subset of jobs to run; default all",
    )
    force: bool = Field(
        default=True,
        description="Bypass/steal lease (default true for manual ticks)",
    )
    scope_tenant: bool = Field(
        default=False,
        description="When true, limit scans to the caller's tenant_id",
    )


def _raise(exc: JobError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/status")
def get_job_status(
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_JOBS_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    status = jobs_service.runner_status(settings=settings)
    status["thread_running"] = job_runner.is_running()
    status["last_tick"] = job_runner.last_tick()
    status["tenant_id"] = tenant.tenant_id
    status["known_jobs"] = list(ALL_JOBS)
    return status


@router.post("/tick")
def post_job_tick(
    request: Request,
    payload: JobTickRequest | None = None,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_JOBS_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    body = payload or JobTickRequest()
    tenant_filter = tenant.tenant_id if body.scope_tenant else None
    try:
        result = jobs_service.run_tick(
            tenant_id=tenant_filter,
            jobs=body.jobs,
            force=body.force,
            settings=settings,
        )
    except JobError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.jobs.tick",
        resource_type="itsm_job_tick",
        resource_id="tick",
        details={
            "forced": body.force,
            "scope_tenant": body.scope_tenant,
            "jobs": body.jobs or list(ALL_JOBS),
            "skipped_jobs": result.get("skipped_jobs"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return result


@router.get("/leases")
def list_leases(
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_JOBS_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    status = jobs_service.runner_status(settings=settings)
    return {
        "items": status.get("leases") or [],
        "count": len(status.get("leases") or []),
        "tenant_id": tenant.tenant_id,
    }
