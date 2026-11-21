"""Dependency traversal and impact analysis APIs (tenant-scoped)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ...auth import require_user
from ..services import ai_cmdb_assist as ai_cmdb_assist_service
from ..services import dependencies as dependencies_service
from ..services.dependencies import DependencyError
from ...tenant_context import TenantContext, require_tenant

router = APIRouter(
    prefix="/api/dependencies",
    tags=["cmdb-dependencies"],
    dependencies=[Depends(require_user)],
)


def _raise(exc: DependencyError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


class ImpactNarrativeRequest(BaseModel):
    component_id: str = Field(min_length=1, max_length=128)
    depth: int = Field(default=10, ge=0, le=50)
    environment: str | None = None
    status: str | None = None
    table: str | None = None
    force_fallback: bool = False


class ChangeRiskRequest(BaseModel):
    component_ids: list[str] = Field(min_length=1, max_length=6)
    change_type: str | None = Field(default=None, max_length=64)
    window_text: str | None = Field(default=None, max_length=2000)
    depth: int = Field(default=10, ge=0, le=50)
    force_fallback: bool = False


@router.post("/ai/impact-narrative")
def impact_narrative(
    payload: ImpactNarrativeRequest,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Assist-only narrative over existing analyze_impact graph (C3)."""
    try:
        return ai_cmdb_assist_service.narrate_impact(
            payload.component_id,
            tenant_id=tenant.tenant_id,
            depth=payload.depth,
            environment=payload.environment,
            status=payload.status,
            table=payload.table,
            force_fallback=bool(payload.force_fallback),
        )
    except DependencyError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/ai/change-risk")
def change_risk(
    payload: ChangeRiskRequest,
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Assist-only change risk text from topology (C4). Never auto-approves."""
    try:
        return ai_cmdb_assist_service.suggest_change_risk(
            payload.component_ids,
            tenant_id=tenant.tenant_id,
            change_type=payload.change_type,
            window_text=payload.window_text,
            depth=payload.depth,
            force_fallback=bool(payload.force_fallback),
        )
    except DependencyError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{component_id}/upstream")
def upstream(
    component_id: str,
    depth: int = Query(default=5, ge=0, le=50),
    environment: str | None = Query(default=None),
    status: str | None = Query(default=None),
    table: str | None = Query(
        default=None,
        description="Optional CMDB type or custom table_key for the starting entity",
    ),
    direct_only: bool = Query(default=False),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Upstream dependencies (follow source → target outgoing edges)."""
    try:
        effective_depth = 1 if direct_only else depth
        return dependencies_service.get_upstream(
            component_id,
            tenant_id=tenant.tenant_id,
            depth=effective_depth,
            environment=environment,
            status=status,
            table=table,
        )
    except DependencyError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{component_id}/downstream")
def downstream(
    component_id: str,
    depth: int = Query(default=5, ge=0, le=50),
    environment: str | None = Query(default=None),
    status: str | None = Query(default=None),
    table: str | None = Query(
        default=None,
        description="Optional CMDB type or custom table_key for the starting entity",
    ),
    direct_only: bool = Query(default=False),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Downstream dependants (follow incoming edges where component is target)."""
    try:
        effective_depth = 1 if direct_only else depth
        return dependencies_service.get_downstream(
            component_id,
            tenant_id=tenant.tenant_id,
            depth=effective_depth,
            environment=environment,
            status=status,
            table=table,
        )
    except DependencyError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{component_id}/impact")
def impact(
    component_id: str,
    depth: int = Query(default=10, ge=0, le=50),
    environment: str | None = Query(default=None),
    status: str | None = Query(default=None),
    table: str | None = Query(
        default=None,
        description="Optional CMDB type or custom table_key for the starting entity",
    ),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Potentially affected applications if this component becomes unavailable."""
    try:
        return dependencies_service.analyze_impact(
            component_id,
            tenant_id=tenant.tenant_id,
            depth=depth,
            environment=environment,
            status=status,
            table=table,
        )
    except DependencyError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{component_id}")
def dependency_overview(
    component_id: str,
    depth: int = Query(default=5, ge=0, le=50),
    environment: str | None = Query(default=None),
    status: str | None = Query(default=None),
    table: str | None = Query(
        default=None,
        description="Optional CMDB type or custom table_key for the starting entity",
    ),
    tenant: TenantContext = Depends(require_tenant),
) -> dict[str, Any]:
    """Combined upstream, downstream, impact, and graph payload for the UI."""
    try:
        return dependencies_service.dependency_bundle(
            component_id,
            tenant_id=tenant.tenant_id,
            depth=depth,
            environment=environment,
            status=status,
            table=table,
        )
    except DependencyError as exc:
        _raise(exc)
        raise  # pragma: no cover
