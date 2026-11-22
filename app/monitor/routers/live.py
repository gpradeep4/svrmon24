"""Live probe stubs — fail-closed 403 unless platform + tenant gates on.

HTTP log ingest lives in ``routers.ingest`` (L3). Agent metrics / file-events
ingest also live in ``routers.ingest`` (L5). Check run-once is in
``routers.checks`` (L1). This module keeps the L0 probe stub only.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...config import Settings, get_settings
from ...permissions import (
    PERM_MONITOR_ADMIN,
    require_permission,
)
from ...tenant_context import TenantContext
from ..services import live_gates as live_gates_service

router = APIRouter(tags=["monitor-live"])


@router.post("/live/probe-stub")
def live_probe_stub(
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """L0 acceptance stub: 403 when gates off; 200 + LIVE marker when both on."""
    live_gates_service.require_live_capability(
        tenant_id=tenant.tenant_id,
        capability="live_stub",
        settings=settings,
    )
    return {
        "ok": True,
        "stub": True,
        "kind": "probe_stub",
        "execution_mode": "LIVE",
        "live_probes": True,
        "tenant_id": tenant.tenant_id,
        "message": (
            "Live gates open — stub only; real polls/ingest land in later L* slices."
        ),
        "live_gates": live_gates_service.live_gates(
            tenant_id=tenant.tenant_id, settings=settings
        ),
    }
