"""Aggregate ITSM API router under ``/api/itsm``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...auth import require_user
from . import activities, dashboard, incidents

router = APIRouter(
    prefix="/api/itsm",
    tags=["itsm"],
    dependencies=[Depends(require_user)],
)

# Register static prefixes before the polymorphic /{ticket_type}/... activity routes.
router.include_router(incidents.router)
router.include_router(dashboard.router)
router.include_router(activities.router)
