"""Aggregate Service Portal API router under ``/api/portal``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...auth import require_user
from . import audit, catalog, changes, executions, meta, requests

router = APIRouter(
    prefix="/api/portal",
    tags=["portal"],
    dependencies=[Depends(require_user)],
)

router.include_router(meta.router)
router.include_router(catalog.router)
router.include_router(requests.router)
router.include_router(changes.router)
router.include_router(executions.router)
router.include_router(audit.router)
