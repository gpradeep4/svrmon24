"""Dispatch LIVE runs to AGENT or AGENTLESS adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ....config import Settings, get_settings
from .. import live_gates as live_gates_service
from . import agent as agent_adapter
from . import agentless as agentless_adapter


class AdapterError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class AdapterResult:
    result_summary: str
    result_detail: dict[str, Any]
    provisioned_facts: dict[str, Any]
    ok: bool = True


def execute_live(
    *,
    run: dict[str, Any],
    req: dict[str, Any],
    tenant_id: str,
    settings: Settings | None = None,
) -> AdapterResult:
    """Run the LIVE (or live DRY_RUN) adapter for a queued/running execution."""
    cfg = settings or get_settings()
    collect = str(run.get("collect_mode") or req.get("collect_mode") or "agentless").lower()
    capability = "agent" if collect == "agent" else "agentless"
    try:
        live_gates_service.assert_live_allowed(
            tenant_id=tenant_id, capability=capability, settings=cfg
        )
    except Exception as exc:  # noqa: BLE001 — HTTPException from gates
        status = getattr(exc, "status_code", 403) or 403
        detail = getattr(exc, "detail", None) or str(exc)
        raise AdapterError(str(detail), status_code=int(status)) from exc

    try:
        if collect == "agent":
            raw = agent_adapter.execute_agent(
                run=run, req=req, tenant_id=tenant_id
            )
        else:
            raw = agentless_adapter.execute_agentless(
                run=run, req=req, settings=cfg
            )
    except (
        agent_adapter.AgentAdapterError,
        agentless_adapter.AgentlessError,
    ) as exc:
        raise AdapterError(exc.message, status_code=exc.status_code) from exc

    if not raw.get("ok", True):
        raise AdapterError(
            str(raw.get("result_summary") or "live adapter failed"),
            status_code=400,
        )
    return AdapterResult(
        ok=True,
        result_summary=str(raw.get("result_summary") or "LIVE ok"),
        result_detail=dict(raw.get("result_detail") or {}),
        provisioned_facts=dict(raw.get("provisioned_facts") or {}),
    )
