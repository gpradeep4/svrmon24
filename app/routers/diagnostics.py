"""Diagnostic APIs — SIMULATED / demo only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from pydantic import BaseModel, Field

from ..auth import require_user
from ..models.diagnostics import DiagnosticStartRequest
from ..services import ai_analysis as ai_analysis_service
from ..services import diagnostics as diagnostics_service
from ..services.ai_analysis import AnalysisError
from ..services.diagnostics import DiagnosticError
from ..services.ollama_client import OllamaClient

router = APIRouter(
    prefix="/api/diagnostics",
    tags=["diagnostics"],
    dependencies=[Depends(require_user)],
)


class AnalyzeRequest(BaseModel):
    force_fallback: bool = Field(
        default=False,
        description="If true, skip Ollama and use deterministic rule-based fallback.",
    )


def _raise(exc: DiagnosticError | AnalysisError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/profiles")
def get_profiles() -> dict[str, Any]:
    return diagnostics_service.list_diagnostic_profiles()


@router.get("/ollama/status")
def ollama_status() -> dict[str, Any]:
    """Probe configured local Ollama endpoint (does not run analysis)."""
    return OllamaClient.from_settings().is_available()


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


@router.post("/{diagnostic_id}/analyze")
def analyze_diagnostic(
    diagnostic_id: str,
    payload: AnalyzeRequest | None = None,
) -> dict[str, Any]:
    """Run AI analysis (Ollama) with rule-based fallback; store on the diagnostic."""
    try:
        return ai_analysis_service.analyze_diagnostic(
            diagnostic_id,
            force_fallback=bool(payload.force_fallback) if payload else False,
        )
    except AnalysisError as exc:
        _raise(exc)
        raise  # pragma: no cover
    except DiagnosticError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/{diagnostic_id}")
def get_diagnostic(diagnostic_id: str) -> dict[str, Any]:
    doc = diagnostics_service.get_diagnostic(diagnostic_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Diagnostic '{diagnostic_id}' not found"
        )
    return doc
