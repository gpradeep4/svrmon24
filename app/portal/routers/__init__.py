"""Aggregate Service Portal API router under ``/api/portal``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...auth import require_user
from . import catalog, meta

router = APIRouter(
    prefix="/api/portal",
    tags=["portal"],
    dependencies=[Depends(require_user)],
)

router.include_router(meta.router)
router.include_router(catalog.router)
