"""Vulnerability scan reports + synthetic findings (SP11 / SM-167a).

Scan one or bulk servers → ``sp_vuln_reports`` with findings and per-vuln
suggestions. Fix/rollback land in SP12.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from .indexes import VULN_REPORTS, ensure_portal_indexes

# Allowlisted synthetic CVE catalog (OD-16) — assist suggestions only.
SYNTHETIC_VULNS: tuple[dict[str, str], ...] = (
    {
        "vuln_id": "CVE-2024-5535",
        "severity": "critical",
        "package": "openssl",
        "title": "OpenSSL SSL_select_next_proto overread",
        "suggestion": "Upgrade openssl to a patched release (≥ 3.0.15) and restart TLS services.",
    },
    {
        "vuln_id": "CVE-2024-6387",
        "severity": "high",
        "package": "openssh",
        "title": "OpenSSH regreSSHion race condition",
        "suggestion": "Upgrade openssh-server; set LoginGraceTime 0 as interim hardening.",
    },
    {
        "vuln_id": "CVE-2023-44487",
        "severity": "high",
        "package": "nginx",
        "title": "HTTP/2 Rapid Reset DoS",
        "suggestion": "Upgrade nginx to a fixed build and disable HTTP/2 if unused.",
    },
    {
        "vuln_id": "CVE-2024-3094",
        "severity": "critical",
        "package": "xz",
        "title": "XZ Utils backdoor (liblzma)",
        "suggestion": "Verify xz/liblzma package integrity; reinstall from trusted mirror if tainted.",
    },
    {
        "vuln_id": "CVE-2024-21626",
        "severity": "high",
        "package": "runc",
        "title": "runc container escape via file descriptor",
        "suggestion": "Upgrade runc / container runtime to the vendor-fixed version.",
    },
    {
        "vuln_id": "CVE-2022-0847",
        "severity": "medium",
        "package": "linux-kernel",
        "title": "Dirty Pipe privilege escalation",
        "suggestion": "Apply kernel security updates and reboot into the patched kernel.",
    },
    {
        "vuln_id": "CVE-2021-44228",
        "severity": "critical",
        "package": "log4j",
        "title": "Log4Shell remote code execution",
        "suggestion": "Upgrade Log4j to ≥ 2.17.1 or remove JndiLookup from the classpath.",
    },
    {
        "vuln_id": "CVE-2023-38545",
        "severity": "medium",
        "package": "curl",
        "title": "libcurl SOCKS5 heap buffer overflow",
        "suggestion": "Upgrade curl/libcurl to ≥ 8.4.0.",
    },
)


class VulnError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _reports() -> Collection:
    ensure_portal_indexes()
    return require_itsm_database()[VULN_REPORTS]


def _new_report_id() -> str:
    return f"SPVR-{uuid.uuid4().hex[:12].upper()}"


def _new_finding_id() -> str:
    return f"SPVF-{uuid.uuid4().hex[:10].upper()}"


def _pick_vulns(component_id: str, *, limit: int = 3) -> list[dict[str, str]]:
    digest = hashlib.sha256(component_id.encode("utf-8")).hexdigest()
    start = int(digest[:8], 16) % len(SYNTHETIC_VULNS)
    out: list[dict[str, str]] = []
    for i in range(max(1, min(limit, len(SYNTHETIC_VULNS)))):
        out.append(dict(SYNTHETIC_VULNS[(start + i) % len(SYNTHETIC_VULNS)]))
    return out


def _parse_component_ids(values: dict[str, Any], *, scope: str) -> list[str]:
    ids: list[str] = []
    if scope == "one":
        ci = values.get("target_ci") or values.get("component_id")
        if ci:
            ids.append(str(ci).strip())
    else:
        raw = values.get("component_ids") or values.get("target_cis") or ""
        if isinstance(raw, list):
            ids.extend(str(x).strip() for x in raw if str(x).strip())
        else:
            for part in str(raw).replace("\n", ",").split(","):
                token = part.strip()
                if token:
                    ids.append(token)
        single = values.get("target_ci")
        if single and str(single).strip() not in ids:
            ids.insert(0, str(single).strip())
    # Dedupe preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for cid in ids:
        if cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    return ordered


def build_scan_findings(
    *,
    component_ids: list[str],
    collect_mode: str,
    live: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (findings, suggestions) for the given CIs."""
    findings: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    for cid in component_ids:
        for vuln in _pick_vulns(cid):
            finding_id = _new_finding_id()
            finding = {
                "finding_id": finding_id,
                "vuln_id": vuln["vuln_id"],
                "component_id": cid,
                "severity": vuln["severity"],
                "package": vuln["package"],
                "title": vuln["title"],
                "status": "open",
                "collect_mode": collect_mode,
                "data_source": "LIVE_SCAN" if live else "SYNTHETIC_DEMO",
            }
            findings.append(finding)
            suggestions.append(
                {
                    "finding_id": finding_id,
                    "vuln_id": vuln["vuln_id"],
                    "component_id": cid,
                    "suggestion": vuln["suggestion"],
                    "action_hint": "vuln.fix.apply",
                }
            )
    return findings, suggestions


def create_report_from_scan(
    *,
    tenant_id: str,
    request_id: str | None,
    run_id: str | None,
    scope: str,
    component_ids: list[str],
    collect_mode: str,
    live: bool,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if not component_ids:
        raise VulnError("scan requires at least one component_id", status_code=400)
    if len(component_ids) > 50:
        raise VulnError("bulk scan limited to 50 servers per request", status_code=400)

    findings, suggestions = build_scan_findings(
        component_ids=component_ids,
        collect_mode=collect_mode,
        live=live,
    )
    now = _now()
    who = (actor or {}).get("user_id") or (actor or {}).get("username")
    doc: dict[str, Any] = {
        "report_id": _new_report_id(),
        "request_id": request_id,
        "run_id": run_id,
        "scope": scope if scope in ("one", "bulk") else "one",
        "component_ids": component_ids,
        "findings": findings,
        "suggestions": suggestions,
        "finding_count": len(findings),
        "status": "completed",
        "collect_mode": collect_mode,
        "execution_mode": "LIVE" if live else "SIMULATED",
        "created_at": now,
        "updated_at": now,
        "created_by": who,
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _reports().insert_one(doc)
    return serialize_document(doc)  # type: ignore[return-value]


def get_report(*, tenant_id: str, report_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    doc = _reports().find_one(merge_tenant_filter({"report_id": report_id}, tid))
    if not doc:
        raise VulnError("vulnerability report not found", status_code=404)
    return serialize_document(doc)  # type: ignore[return-value]


def list_reports(
    *,
    tenant_id: str,
    request_id: str | None = None,
    component_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    clauses: list[dict[str, Any]] = []
    if request_id:
        clauses.append({"request_id": request_id})
    if component_id:
        clauses.append({"component_ids": component_id})
    base = {"$and": clauses} if clauses else None
    query = merge_tenant_filter(base, tid)
    coll = _reports()
    total = coll.count_documents(query)
    skip = max(0, (page - 1) * page_size)
    cursor = (
        coll.find(query)
        .sort([("created_at", -1)])
        .skip(skip)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def run_scan_for_request(
    *,
    tenant_id: str,
    req: dict[str, Any],
    run: dict[str, Any],
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute scan for a portal request/run and persist the report."""
    action = str(run.get("action_key") or req.get("action_key") or "")
    scope = "bulk" if action.endswith(".bulk") or "bulk" in action else "one"
    values = dict(req.get("form_values") or {})
    component_ids = _parse_component_ids(values, scope=scope)
    if not component_ids and req.get("component_id"):
        component_ids = [str(req["component_id"])]
    if not component_ids:
        raise VulnError(
            "vulnerability scan requires target_ci or component_ids",
            status_code=400,
        )
    exec_mode = str(run.get("execution_mode") or "SIMULATED").upper()
    dry_run = bool(run.get("dry_run") or exec_mode == "DRY_RUN")
    live = exec_mode == "LIVE"
    collect = str(run.get("collect_mode") or req.get("collect_mode") or "agentless")

    if dry_run:
        findings, suggestions = build_scan_findings(
            component_ids=component_ids,
            collect_mode=collect,
            live=live,
        )
        summary = (
            f"DRY_RUN vuln scan plan ({scope}) — would report "
            f"{len(findings)} findings across {len(component_ids)} server(s)"
        )
        return {
            "ok": True,
            "result_summary": summary,
            "result_detail": {
                "steps": [
                    {"step": "validate_targets", "ok": True, "count": len(component_ids)},
                    {"step": "plan", "ok": True, "finding_count": len(findings)},
                ],
                "stdout": f"[vuln] dry-run plan findings={len(findings)}",
                "stderr": "",
                "planned_suggestions_sample": suggestions[:5],
            },
            "provisioned_facts": {
                "path": collect,
                "action_key": action,
                "finding_count": len(findings),
                "component_ids": component_ids,
                "scope": scope,
                "dry_run": True,
                "live": live,
                "simulated": not live,
            },
        }

    report = create_report_from_scan(
        tenant_id=tenant_id,
        request_id=req.get("request_id"),
        run_id=run.get("run_id"),
        scope=scope,
        component_ids=component_ids,
        collect_mode=collect,
        live=live,
        actor=actor,
    )
    summary = (
        f"{'LIVE' if live else 'SIMULATED'} vuln scan ({scope}) — "
        f"{report['finding_count']} findings across {len(component_ids)} server(s)"
    )
    return {
        "ok": True,
        "result_summary": summary,
        "result_detail": {
            "steps": [
                {"step": "validate_targets", "ok": True, "count": len(component_ids)},
                {
                    "step": "scan",
                    "ok": True,
                    "mode": "LIVE" if live else "SIMULATED",
                    "collect_mode": collect,
                },
                {"step": "persist_report", "ok": True, "report_id": report["report_id"]},
            ],
            "stdout": f"[vuln] report {report['report_id']} findings={report['finding_count']}",
            "stderr": "",
        },
        "provisioned_facts": {
            "path": collect,
            "action_key": action,
            "report_id": report["report_id"],
            "finding_count": report["finding_count"],
            "component_ids": component_ids,
            "scope": scope,
            "live": live,
            "simulated": not live,
        },
        "report": report,
    }
