"""Diagnostic APIs — SIMULATED / demo only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import verify_basic_credentials
from ..models.diagnostics import DiagnosticStartRequest
from ..services import diagnostics as diagnostics_service
from ..services.diagnostics import DiagnosticError

router = APIRouter(
    prefix="/api/diagnostics",
    tags=["diagnostics"],
    dependencies=[Depends(verify_basic_credentials)],
)


def _raise(exc: DiagnosticError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/profiles")
def get_profiles() -> dict[str, Any]:
    return diagnostics_service.list_diagnostic_profiles()


@router.post("", status_code=201)
def start_diagnostic(payload: DiagnosticStartRequest) -> dict[str, Any]:
    try:
        return diagnostics_service.start_diagnostic(payload)
    except DiagnosticError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("")
def list_history(
    component_id: str | None = Query(default=None),
    profile_name: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
) -> dict[str, Any]:
    return diagnostics_service.list_diagnostics(
        component_id=component_id,
        profile_name=profile_name,
        page=page,
        page_size=page_size,
    )


@router.get("/{diagnostic_id}")
def get_diagnostic(diagnostic_id: str) -> dict[str, Any]:
    doc = diagnostics_service.get_diagnostic(diagnostic_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Diagnostic '{diagnostic_id}' not found"
        )
    return doc
