"""Dependency traversal and impact analysis APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_user
from ..services import dependencies as dependencies_service
from ..services.dependencies import DependencyError

router = APIRouter(
    prefix="/api/dependencies",
    tags=["cmdb-dependencies"],
    dependencies=[Depends(require_user)],
)


def _raise(exc: DependencyError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{component_id}/upstream")
def upstream(
    component_id: str,
    depth: int = Query(default=5, ge=0, le=50),
    environment: str | None = Query(default=None),
    status: str | None = Query(default=None),
    direct_only: bool = Query(default=False),
) -> dict[str, Any]:
    """Upstream dependencies (follow source → target outgoing edges)."""
    try:
        effective_depth = 1 if direct_only else depth
        return dependencies_service.get_upstream(
            component_id,
            depth=effective_depth,
            environment=environment,
            status=status,
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
    direct_only: bool = Query(default=False),
) -> dict[str, Any]:
    """Downstream dependants (follow incoming edges where component is target)."""
    try:
        effective_depth = 1 if direct_only else depth
        return dependencies_service.get_downstream(
            component_id,
            depth=effective_depth,
            environment=environment,
            status=status,
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
) -> dict[str, Any]:
    """Potentially affected applications if this component becomes unavailable."""
    try:
        return dependencies_service.analyze_impact(
            component_id,
            depth=depth,
            environment=environment,
            status=status,
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
) -> dict[str, Any]:
    """Combined upstream, downstream, impact, and graph payload for the UI."""
    try:
        return dependencies_service.dependency_bundle(
            component_id,
            depth=depth,
            environment=environment,
            status=status,
        )
    except DependencyError as exc:
        _raise(exc)
        raise  # pragma: no cover
