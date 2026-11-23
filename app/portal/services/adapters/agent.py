"""AGENT LIVE adapters — dispatch allowlisted jobs via Monitoring agents."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from ....db import require_itsm_database
from ....tenancy import require_tenant_id, stamp_tenant_id
from ..indexes import ensure_portal_indexes
from . import terraform_cloud as tf_cloud

AGENT_JOBS = "sp_agent_jobs"


class AgentAdapterError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jobs() -> Collection:
    ensure_portal_indexes()
    return require_itsm_database()[AGENT_JOBS]


def _find_agent(tenant_id: str, *, hostname: str | None) -> dict[str, Any] | None:
    """Best-effort match to a Monitoring agent (API/service client — no cross-DB join)."""
    try:
        from ....monitor.services import agents as agents_service
    except Exception:  # noqa: BLE001
        return None
    try:
        listed = agents_service.list_agents(tenant_id=tenant_id, page=1, page_size=100)
    except Exception:  # noqa: BLE001
        return None
    items = listed.get("items") if isinstance(listed, dict) else listed
    if not isinstance(items, list):
        return None
    if hostname:
        host = hostname.strip().lower()
        for agent in items:
            if str(agent.get("hostname") or "").strip().lower() == host:
                return agent
            if str(agent.get("name") or "").strip().lower() == host:
                return agent
    # Prefer first active agent for lab dispatch.
    for agent in items:
        if str(agent.get("status") or "").lower() in ("active", "online", "ok"):
            return agent
    return items[0] if items else None


def _enqueue_job(
    *,
    tenant_id: str,
    run: dict[str, Any],
    req: dict[str, Any],
    agent: dict[str, Any] | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    job_id = f"SPJOB-{uuid.uuid4().hex[:12].upper()}"
    doc: dict[str, Any] = {
        "job_id": job_id,
        "run_id": run.get("run_id"),
        "request_id": req.get("request_id"),
        "action_key": run.get("action_key") or req.get("action_key"),
        "agent_id": (agent or {}).get("agent_id"),
        "status": "dispatched" if agent else "queued_no_agent",
        "payload": payload,
        "created_at": _now(),
        "updated_at": _now(),
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _jobs().insert_one(doc)
    return doc


def execute_agent(
    *,
    run: dict[str, Any],
    req: dict[str, Any],
    tenant_id: str,
) -> dict[str, Any]:
    """Dispatch allowlisted action to Monitoring agent channel (OD-8)."""
    action = str(run.get("action_key") or req.get("action_key") or "")
    values = dict(req.get("form_values") or {})
    dry_run = bool(run.get("dry_run") or run.get("execution_mode") == "DRY_RUN")

    if action.startswith("vuln.scan."):
        from .. import vuln as vuln_service

        scanned = vuln_service.run_scan_for_request(
            tenant_id=tenant_id,
            req=req,
            run={**run, "execution_mode": "LIVE" if not dry_run else "DRY_RUN"},
        )
        agent = _find_agent(
            tenant_id,
            hostname=str((req.get("form_values") or {}).get("hostname") or "")
            or None,
        )
        job = _enqueue_job(
            tenant_id=tenant_id,
            run=run,
            req=req,
            agent=agent,
            payload={
                "action_key": action,
                "dry_run": dry_run,
                "report_id": (scanned.get("provisioned_facts") or {}).get("report_id"),
            },
        )
        facts = dict(scanned.get("provisioned_facts") or {})
        facts["path"] = "agent"
        facts["agent_job_id"] = job["job_id"]
        facts["agent_id"] = job.get("agent_id")
        detail = dict(scanned.get("result_detail") or {})
        steps = list(detail.get("steps") or [])
        steps.append(
            {
                "step": "agent_dispatch",
                "ok": True,
                "job_id": job["job_id"],
                "agent_id": job.get("agent_id"),
            }
        )
        detail["steps"] = steps
        return {
            "ok": True,
            "result_summary": f"{scanned.get('result_summary')} + agent job {job['job_id']}",
            "provisioned_facts": facts,
            "result_detail": detail,
        }

    # Cloud VM provision on agent path still uses Terraform (control plane),
    # then records an agent acknowledgment job when an agent exists.
    if action == "cloud.vm.provision":
        try:
            tf_result = tf_cloud.provision_vm(values, dry_run=dry_run)
        except tf_cloud.TerraformError as exc:
            raise AgentAdapterError(exc.message, status_code=exc.status_code) from exc
        agent = _find_agent(tenant_id, hostname=str(values.get("hostname") or "") or None)
        job = _enqueue_job(
            tenant_id=tenant_id,
            run=run,
            req=req,
            agent=agent,
            payload={
                "action_key": action,
                "dry_run": dry_run,
                "terraform": True,
                "hostname": values.get("hostname"),
            },
        )
        facts = dict(tf_result.get("provisioned_facts") or {})
        facts["path"] = "agent"
        facts["agent_job_id"] = job["job_id"]
        facts["agent_id"] = job.get("agent_id")
        detail = dict(tf_result.get("result_detail") or {})
        steps = list(detail.get("steps") or [])
        steps.append(
            {
                "step": "agent_dispatch",
                "ok": True,
                "agent_id": job.get("agent_id"),
                "job_id": job["job_id"],
            }
        )
        detail["steps"] = steps
        return {
            "ok": True,
            "result_summary": (
                f"{tf_result.get('result_summary')} + agent job {job['job_id']}"
            ),
            "provisioned_facts": facts,
            "result_detail": detail,
        }

    snap = req.get("component_snapshot") or {}
    hostname = (
        values.get("hostname")
        or snap.get("hostname")
        or snap.get("name")
        or None
    )
    agent = _find_agent(tenant_id, hostname=str(hostname) if hostname else None)
    payload = {
        "action_key": action,
        "dry_run": dry_run,
        "form_values": {
            k: v for k, v in values.items() if not str(k).endswith("_secret")
        },
        "component_id": req.get("component_id") or values.get("target_ci"),
    }
    job = _enqueue_job(
        tenant_id=tenant_id,
        run=run,
        req=req,
        agent=agent,
        payload=payload,
    )
    # Inline completion for unlock v1: job is recorded; agent pulls later.
    # Run succeeds once dispatched (or queued without agent in lab).
    summary = (
        f"LIVE agent {'dry-run' if dry_run else 'dispatch'} {action} "
        f"job={job['job_id']}"
        + (f" agent={job['agent_id']}" if job.get("agent_id") else " (no agent online)")
    )
    return {
        "ok": True,
        "result_summary": summary,
        "provisioned_facts": {
            "path": "agent",
            "action_key": action,
            "agent_job_id": job["job_id"],
            "agent_id": job.get("agent_id"),
            "hostname": hostname,
            "dry_run": dry_run,
            "live": True,
            "simulated": False,
        },
        "result_detail": {
            "steps": [
                {"step": "validate", "ok": True},
                {
                    "step": "agent_dispatch",
                    "ok": True,
                    "job_id": job["job_id"],
                    "agent_id": job.get("agent_id"),
                    "status": job.get("status"),
                },
            ],
            "stdout": f"[agent] {summary}",
            "stderr": "",
        },
    }
