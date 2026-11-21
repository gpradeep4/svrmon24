"""Aggregate Monitoring API router under ``/api/monitor``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...auth import require_user
from . import meta

router = APIRouter(
    prefix="/api/monitor",
    tags=["monitor"],
    dependencies=[Depends(require_user)],
)

router.include_router(meta.router)
