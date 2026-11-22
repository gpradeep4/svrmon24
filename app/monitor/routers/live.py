"""Live probe / ingest stubs — fail-closed 403 unless platform + tenant gates on.

HTTP/TCP check run-once lives in ``routers.checks`` (L1). Remaining stubs
mark ``execution_mode=LIVE`` until later L* slices implement real ingest.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...config import Settings, get_settings
from ...permissions import (
    PERM_MONITOR_ADMIN,
    PERM_MONITOR_LOGS_WRITE,
    PERM_MONITOR_TARGETS_WRITE,
    require_permission,
)
from ...tenant_context import TenantContext
from ..services import live_gates as live_gates_service

router = APIRouter(tags=["monitor-live"])


def _stub_ok(
    *,
    tenant_id: str,
    kind: str,
    settings: Settings,
) -> dict[str, Any]:
    return {
        "ok": True,
        "stub": True,
        "kind": kind,
        "execution_mode": "LIVE",
        "live_probes": True,
        "tenant_id": tenant_id,
        "message": (
            "Live gates open — stub only; real polls/ingest land in later L* slices."
        ),
        "live_gates": live_gates_service.live_gates(
            tenant_id=tenant_id, settings=settings
        ),
    }


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
    return _stub_ok(
        tenant_id=tenant.tenant_id, kind="probe_stub", settings=settings
    )


@router.post("/ingest/logs")
def ingest_logs_stub(
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_LOGS_WRITE)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """HTTP log ingest stub — fail-closed until L3 implements real ingest."""
    live_gates_service.require_live_capability(
        tenant_id=tenant.tenant_id,
        capability="log_ingest_http",
        settings=settings,
    )
    return _stub_ok(
        tenant_id=tenant.tenant_id, kind="ingest_logs", settings=settings
    )


@router.post("/ingest/metrics")
def ingest_metrics_stub(
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_WRITE)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Agent metrics ingest stub — fail-closed until L5."""
    live_gates_service.require_live_capability(
        tenant_id=tenant.tenant_id,
        capability="agent_ingest",
        settings=settings,
    )
    return _stub_ok(
        tenant_id=tenant.tenant_id, kind="ingest_metrics", settings=settings
    )


@router.post("/ingest/file-events")
def ingest_file_events_stub(
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_WRITE)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Agent file-event ingest stub — fail-closed until L5/L6."""
    live_gates_service.require_live_capability(
        tenant_id=tenant.tenant_id,
        capability="agent_ingest",
        settings=settings,
    )
    return _stub_ok(
        tenant_id=tenant.tenant_id, kind="ingest_file_events", settings=settings
    )
