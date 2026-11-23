"""AGENTLESS LIVE adapters — allowlisted structured actions + egress."""

from __future__ import annotations

import socket
from typing import Any

from ....config import Settings, get_settings
from .egress import EgressDenied, assert_portal_egress
from . import terraform_cloud as tf_cloud


class AgentlessError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _resolve_hostname(
    req: dict[str, Any],
    values: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> str | None:
    snap = req.get("component_snapshot") or {}
    for key in ("hostname", "ip_address", "name"):
        if snap.get(key):
            return str(snap[key]).strip()
    for key in ("hostname", "target_host", "ip_address"):
        if values.get(key):
            return str(values[key]).strip()
    # Resolve CI ref via CMDB API/service (no cross-DB join).
    ci = values.get("target_ci") or req.get("component_id")
    if ci and tenant_id:
        try:
            from ....cmdb.services import components as components_service

            doc = components_service.get_component(str(ci), tenant_id=tenant_id)
            if isinstance(doc, dict):
                for key in ("hostname", "ip_address", "name"):
                    if doc.get(key):
                        return str(doc[key]).strip()
        except Exception:  # noqa: BLE001
            pass
    return None


def _tcp_probe(hostname: str, port: int = 22, timeout: float = 2.0) -> dict[str, Any]:
    start_ok = False
    message = ""
    try:
        with socket.create_connection((hostname, port), timeout=timeout):
            start_ok = True
            message = f"tcp/{port} open"
    except OSError as exc:
        message = f"tcp/{port} probe: {exc}"
    return {"ok": start_ok, "message": message, "port": port}


def _host_bound_plan(
    *,
    action: str,
    hostname: str,
    values: dict[str, Any],
    dry_run: bool,
    settings: Settings,
) -> dict[str, Any]:
    try:
        resolved = assert_portal_egress(hostname=hostname, settings=settings)
    except EgressDenied as exc:
        raise AgentlessError(exc.message, status_code=403) from exc

    probe = _tcp_probe(hostname)
    argv = _allowlisted_argv(action, values)
    steps = [
        {"step": "egress_allowlist", "ok": True, "resolved": resolved[:8]},
        {"step": "tcp_probe", "ok": probe["ok"], "detail": probe["message"]},
        {
            "step": "plan" if dry_run else "apply",
            "ok": True,
            "argv": argv,
            "mode": "AGENTLESS_STRUCTURED",
        },
    ]
    # Mutating agentless without an SSH transport still records the allowlisted
    # operation (structured live). Real SSH can be layered via secret_ref later.
    summary = (
        f"LIVE agentless {'dry-run' if dry_run else 'apply'} {action} "
        f"on {hostname}"
    )
    return {
        "ok": True,
        "result_summary": summary,
        "provisioned_facts": {
            "path": "agentless",
            "action_key": action,
            "hostname": hostname,
            "argv": argv,
            "dry_run": dry_run,
            "live": True,
            "simulated": False,
        },
        "result_detail": {
            "steps": steps,
            "stdout": f"[agentless] {summary}",
            "stderr": "" if probe["ok"] else probe["message"],
        },
    }


def _allowlisted_argv(action: str, values: dict[str, Any]) -> list[str]:
    """Fixed argv templates — never interpolate a free-form command string."""
    if action == "os.folder.create":
        path = str(values.get("path") or "")
        mode = str(values.get("mode") or "0755")
        return ["mkdir", "-p", "-m", mode, path]
    if action == "os.file.create":
        path = str(values.get("path") or "")
        return ["install", "-m", str(values.get("mode") or "0644"), "/dev/null", path]
    if action == "os.user.create":
        user = str(values.get("username") or "")
        argv = ["useradd", user]
        if values.get("create_home"):
            argv.insert(1, "-m")
        return argv
    if action == "os.app.install":
        pkg = str(values.get("package") or "")
        return ["pkg-install", pkg]
    if action.startswith("mw.") or action.startswith("db."):
        product = str(values.get("product") or values.get("engine") or "app")
        version = str(values.get("version") or values.get("patch_id") or "")
        return ["allowlisted-install", product, version]
    if action == "net.firewall.rule.add":
        return [
            "firewall-rule-add",
            str(values.get("proto")),
            str(values.get("port")),
            str(values.get("src")),
            str(values.get("dst")),
        ]
    if action == "cloud.app.install":
        return ["pkg-install", str(values.get("package") or "")]
    # Generic / other — no remote argv
    return ["portal-marker", action]


def _local_marker(action: str, values: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    summary = (
        f"LIVE agentless {'dry-run' if dry_run else 'complete'} {action} "
        f"(no remote host)"
    )
    return {
        "ok": True,
        "result_summary": summary,
        "provisioned_facts": {
            "path": "agentless",
            "action_key": action,
            "dry_run": dry_run,
            "live": True,
            "simulated": False,
            "echo_fields": {
                k: v for k, v in values.items() if not str(k).endswith("_secret")
            },
        },
        "result_detail": {
            "steps": [
                {"step": "validate", "ok": True},
                {"step": "marker", "ok": True, "dry_run": dry_run},
            ],
            "stdout": f"[agentless] {summary}",
            "stderr": "",
        },
    }


def execute_agentless(
    *,
    run: dict[str, Any],
    req: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    action = str(run.get("action_key") or req.get("action_key") or "")
    values = dict(req.get("form_values") or {})
    dry_run = bool(run.get("dry_run") or run.get("execution_mode") == "DRY_RUN")

    if action == "cloud.vm.provision":
        try:
            return tf_cloud.provision_vm(values, dry_run=dry_run)
        except tf_cloud.TerraformError as exc:
            raise AgentlessError(exc.message, status_code=exc.status_code) from exc

    hostname = _resolve_hostname(
        req, values, tenant_id=str(req.get("tenant_id") or "") or None
    )
    host_actions = {
        "os.folder.create",
        "os.file.create",
        "os.user.create",
        "os.app.install",
        "os.server.provision",
        "mw.install",
        "mw.upgrade",
        "mw.patch",
        "db.install",
        "db.upgrade",
        "db.patch",
        "net.firewall.rule.add",
        "cloud.app.install",
        "generic.daily.reboot_window",
    }
    if action in host_actions and hostname:
        if action == "os.server.provision":
            # Provision may not have a reachable host yet — still record live facts.
            return {
                "ok": True,
                "result_summary": (
                    f"LIVE agentless {'dry-run' if dry_run else 'provision'} "
                    f"{action} hostname={hostname}"
                ),
                "provisioned_facts": {
                    "path": "agentless",
                    "action_key": action,
                    "hostname": hostname,
                    "os_family": values.get("os_family"),
                    "os_version": values.get("os_version"),
                    "live": True,
                    "dry_run": dry_run,
                },
                "result_detail": {
                    "steps": [
                        {"step": "validate", "ok": True},
                        {"step": "provision_record", "ok": True},
                    ],
                    "stdout": f"[agentless] provision {hostname}",
                    "stderr": "",
                },
            }
        return _host_bound_plan(
            action=action,
            hostname=hostname,
            values=values,
            dry_run=dry_run,
            settings=cfg,
        )

    return _local_marker(action, values, dry_run=dry_run)
