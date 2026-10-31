"""Dashboard summary API — live aggregates for the UI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..auth import require_user
from ..services import dashboard as dashboard_service

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_user)],
)


@router.get("/summary")
def dashboard_summary(
    recent_limit: int = Query(default=8, ge=1, le=50),
) -> dict[str, Any]:
    """Return live dashboard widget data (no hardcoded counts)."""
    return dashboard_service.get_dashboard_summary(recent_limit=recent_limit)
