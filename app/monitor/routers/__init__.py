"""Aggregate Monitoring API router under ``/api/monitor``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...auth import require_user
from . import admin, agents, alerts, checks, dashboard, ingest, live, logs, meta, targets

router = APIRouter(
    prefix="/api/monitor",
    tags=["monitor"],
)

# Session/Basic-authenticated Monitoring routes.
_secured = APIRouter(dependencies=[Depends(require_user)])
_secured.include_router(meta.router)
_secured.include_router(dashboard.router)
_secured.include_router(targets.router)
_secured.include_router(logs.router)
_secured.include_router(alerts.router)
_secured.include_router(checks.router)
_secured.include_router(agents.router)
_secured.include_router(admin.router)
_secured.include_router(live.router)

router.include_router(_secured)
# Dual-auth HTTP log ingest (session or ingest key) — no global require_user.
router.include_router(ingest.router)
# Agent register / heartbeat / rotate (enrollment code, agent token, or mTLS sketch).
router.include_router(agents.public_router)
