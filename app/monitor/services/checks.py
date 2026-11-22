"""Agentless monitor_checks CRUD + LIVE run/write (L1 HTTP/TCP + L2 ICMP/SNMP)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import DESCENDING
from pymongo.collection import Collection

from ...config import Settings, get_settings
from ...serialization import serialize_document
from ...services import entitlements as entitlements_service
from ...services.entitlements import EntitlementError
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id, tenant_filter
from ..models.checks import L2_PROTOCOLS
from . import executors
from .indexes import ensure_monitor_indexes
from .live_gates import live_allowed
from .secrets import SecretRefError, normalize_secret_ref

CHECKS_COLLECTION = "monitor_checks"
RESULTS_COLLECTION = "monitor_check_results"
SAMPLES_COLLECTION = "metric_samples"
TARGETS_COLLECTION = "monitor_targets"

DEFAULT_INTERVAL = 60
DEFAULT_TIMEOUT = 5
MIN_INTERVAL = 5
MAX_INTERVAL = 86400
MIN_TIMEOUT = 1
MAX_TIMEOUT = 120


class MonitorChecksError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_check_id() -> str:
    return f"chk-{uuid.uuid4().hex[:12]}"


def _new_result_id() -> str:
    return f"cr-{uuid.uuid4().hex[:12]}"


def _new_sample_id() -> str:
    return f"ms-{uuid.uuid4().hex[:12]}"


def _checks() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[CHECKS_COLLECTION]


def _results() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[RESULTS_COLLECTION]


def _samples() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[SAMPLES_COLLECTION]


def _targets() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[TARGETS_COLLECTION]


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    return serialize_document(doc)


def count_monitor_checks(*, tenant_id: str) -> int:
    tid = require_tenant_id(tenant_id)
    return int(_checks().count_documents(tenant_filter(tid)))


def assert_can_create_monitor_check(tenant_id: str) -> None:
    """Enforce ``monitor_live_checks`` entitlement before creating a check."""
    tid = require_tenant_id(tenant_id)
    limit = entitlements_service.monitor_live_checks_limit(tid)
    if limit is None:
        return
    total = count_monitor_checks(tenant_id=tid)
    if total >= limit:
        raise EntitlementError(
            f"Live check limit reached for this tenant "
            f"({total}/{limit}). Upgrade entitlements to create more checks.",
            status_code=403,
        )


def _normalize_protocol(raw: Any) -> str:
    proto = str(raw or "").strip().lower()
    if proto not in L2_PROTOCOLS:
        raise MonitorChecksError(
            f"protocol must be one of: {', '.join(L2_PROTOCOLS)}",
            status_code=422,
        )
    return proto


def _normalize_endpoint(raw: Any, *, protocol: str) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise MonitorChecksError("endpoint must be an object", status_code=422)
    out: dict[str, Any] = {}
    for key in ("url", "host", "path", "method", "oid", "snmp_version"):
        val = raw.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            out[key] = text
    if raw.get("port") is not None:
        try:
            out["port"] = int(raw["port"])
        except (TypeError, ValueError) as exc:
            raise MonitorChecksError("endpoint.port must be an integer", status_code=422) from exc
    if raw.get("expect_status") is not None:
        try:
            out["expect_status"] = int(raw["expect_status"])
        except (TypeError, ValueError) as exc:
            raise MonitorChecksError(
                "endpoint.expect_status must be an integer", status_code=422
            ) from exc

    if protocol == "http":
        if not out.get("url") and not out.get("host"):
            raise MonitorChecksError(
                "http endpoint requires url or host", status_code=422
            )
    elif protocol == "tcp":
        if not out.get("host") and not out.get("url"):
            raise MonitorChecksError(
                "tcp endpoint requires host (or url)", status_code=422
            )
        if out.get("port") is None and not out.get("url"):
            raise MonitorChecksError("tcp endpoint requires port", status_code=422)
    elif protocol == "icmp":
        if not out.get("host") and not out.get("url"):
            raise MonitorChecksError(
                "icmp endpoint requires host (or url)", status_code=422
            )
    elif protocol == "snmp":
        if not out.get("host") and not out.get("url"):
            raise MonitorChecksError(
                "snmp endpoint requires host (or url)", status_code=422
            )
        if not out.get("oid"):
            out["oid"] = executors.DEFAULT_SNMP_OID
        if out.get("port") is None:
            out["port"] = executors.DEFAULT_SNMP_PORT
        if not out.get("snmp_version"):
            out["snmp_version"] = "2c"
    return out


def _normalize_secret_ref_fields(raw: Any) -> tuple[str | None, bool]:
    try:
        return normalize_secret_ref(raw)
    except SecretRefError as exc:
        raise MonitorChecksError(exc.message, status_code=422) from exc


def _normalize_allowlist(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return parts
    if isinstance(raw, list):
        return [str(p).strip() for p in raw if str(p).strip()]
    raise MonitorChecksError("egress_allowlist must be a list or string", status_code=422)


def _clamp_int(raw: Any, *, default: int, lo: int, hi: int, field: str) -> int:
    if raw is None:
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError) as exc:
        raise MonitorChecksError(f"{field} must be an integer", status_code=422) from exc
    if val < lo or val > hi:
        raise MonitorChecksError(
            f"{field} must be between {lo} and {hi}", status_code=422
        )
    return val


def list_checks(
    *,
    tenant_id: str,
    protocol: str | None = None,
    enabled: bool | None = None,
    target_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    query: dict[str, Any] = {}
    if enabled is not None:
        query["enabled"] = bool(enabled)
    if protocol:
        query["protocol"] = str(protocol).strip().lower()
    if target_id:
        query["target_id"] = str(target_id).strip()
    filt = merge_tenant_filter(query, tid)
    coll = _checks()
    total = coll.count_documents(filt)
    cursor = (
        coll.find(filt)
        .sort([("updated_at", DESCENDING), ("check_id", DESCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [_serialize(doc) for doc in cursor]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_check(*, tenant_id: str, check_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    cid = str(check_id or "").strip()
    if not cid:
        return None
    doc = _checks().find_one(merge_tenant_filter({"check_id": cid}, tid))
    return _serialize(doc)


def create_check(*, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    assert_can_create_monitor_check(tid)
    target_id = str(payload.get("target_id") or "").strip()
    if not target_id:
        raise MonitorChecksError("target_id is required", status_code=422)
    protocol = _normalize_protocol(payload.get("protocol"))
    endpoint = _normalize_endpoint(payload.get("endpoint"), protocol=protocol)
    component_id = payload.get("component_id")
    if component_id is not None:
        component_id = str(component_id).strip() or None
    secret_ref, secret_insecure_demo = _normalize_secret_ref_fields(
        payload.get("secret_ref")
    )
    if protocol == "snmp" and not secret_ref:
        raise MonitorChecksError(
            "snmp checks require secret_ref (env:VAR or insecure: for lab)",
            status_code=422,
        )
    interval = _clamp_int(
        payload.get("interval_seconds"),
        default=DEFAULT_INTERVAL,
        lo=MIN_INTERVAL,
        hi=MAX_INTERVAL,
        field="interval_seconds",
    )
    timeout = _clamp_int(
        payload.get("timeout_seconds"),
        default=DEFAULT_TIMEOUT,
        lo=MIN_TIMEOUT,
        hi=MAX_TIMEOUT,
        field="timeout_seconds",
    )
    enabled = bool(payload.get("enabled", True))
    egress_allowlist = _normalize_allowlist(payload.get("egress_allowlist"))
    now = _now()
    check_id = _new_check_id()
    doc = stamp_tenant_id(
        {
            "check_id": check_id,
            "target_id": target_id,
            "component_id": component_id,
            "collect_mode": "AGENTLESS",
            "protocol": protocol,
            "endpoint": endpoint,
            "secret_ref": secret_ref,
            "secret_insecure_demo": secret_insecure_demo,
            "interval_seconds": interval,
            "timeout_seconds": timeout,
            "enabled": enabled,
            "egress_allowlist": egress_allowlist,
            "last_run_at": None,
            "last_result": None,
            "created_at": now,
            "updated_at": now,
        },
        tenant_id=tid,
    )
    _checks().insert_one(doc)
    _link_check_to_target(tenant_id=tid, target_id=target_id, check_id=check_id)
    return _serialize(doc)  # type: ignore[return-value]


def patch_check(
    *,
    tenant_id: str,
    check_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    cid = str(check_id or "").strip()
    existing = _checks().find_one(merge_tenant_filter({"check_id": cid}, tid))
    if existing is None:
        raise MonitorChecksError(f"Check '{cid}' not found", status_code=404)
    updates: dict[str, Any] = {}
    if "target_id" in payload and payload["target_id"] is not None:
        target_id = str(payload["target_id"]).strip()
        if not target_id:
            raise MonitorChecksError("target_id cannot be empty", status_code=422)
        updates["target_id"] = target_id
    if "component_id" in payload:
        component_id = payload["component_id"]
        updates["component_id"] = (
            str(component_id).strip() or None if component_id is not None else None
        )
    protocol = existing.get("protocol")
    if "protocol" in payload and payload["protocol"] is not None:
        protocol = _normalize_protocol(payload["protocol"])
        updates["protocol"] = protocol
    if "endpoint" in payload and payload["endpoint"] is not None:
        updates["endpoint"] = _normalize_endpoint(
            payload["endpoint"], protocol=str(protocol)
        )
    if "secret_ref" in payload:
        secret_ref, secret_insecure_demo = _normalize_secret_ref_fields(
            payload["secret_ref"]
        )
        updates["secret_ref"] = secret_ref
        updates["secret_insecure_demo"] = secret_insecure_demo
    effective_protocol = str(updates.get("protocol") or existing.get("protocol") or "")
    effective_secret = (
        updates["secret_ref"] if "secret_ref" in updates else existing.get("secret_ref")
    )
    if effective_protocol == "snmp" and not effective_secret:
        raise MonitorChecksError(
            "snmp checks require secret_ref (env:VAR or insecure: for lab)",
            status_code=422,
        )
    if "interval_seconds" in payload:
        updates["interval_seconds"] = _clamp_int(
            payload["interval_seconds"],
            default=DEFAULT_INTERVAL,
            lo=MIN_INTERVAL,
            hi=MAX_INTERVAL,
            field="interval_seconds",
        )
    if "timeout_seconds" in payload:
        updates["timeout_seconds"] = _clamp_int(
            payload["timeout_seconds"],
            default=DEFAULT_TIMEOUT,
            lo=MIN_TIMEOUT,
            hi=MAX_TIMEOUT,
            field="timeout_seconds",
        )
    if "enabled" in payload and payload["enabled"] is not None:
        updates["enabled"] = bool(payload["enabled"])
    if "egress_allowlist" in payload:
        updates["egress_allowlist"] = _normalize_allowlist(payload["egress_allowlist"])
    if not updates:
        return _serialize(existing)  # type: ignore[return-value]
    updates["updated_at"] = _now()
    _checks().update_one(
        merge_tenant_filter({"check_id": cid}, tid), {"$set": updates}
    )
    doc = _checks().find_one(merge_tenant_filter({"check_id": cid}, tid))
    return _serialize(doc)  # type: ignore[return-value]


def delete_check(*, tenant_id: str, check_id: str) -> bool:
    tid = require_tenant_id(tenant_id)
    cid = str(check_id or "").strip()
    result = _checks().delete_one(merge_tenant_filter({"check_id": cid}, tid))
    return result.deleted_count > 0


def list_check_results(
    *,
    tenant_id: str,
    check_id: str,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    cid = str(check_id or "").strip()
    if get_check(tenant_id=tid, check_id=cid) is None:
        raise MonitorChecksError(f"Check '{cid}' not found", status_code=404)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    filt = merge_tenant_filter({"check_id": cid}, tid)
    coll = _results()
    total = coll.count_documents(filt)
    cursor = (
        coll.find(filt)
        .sort([("observed_at", DESCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [_serialize(doc) for doc in cursor],
        "total": total,
        "page": page,
        "page_size": page_size,
        "check_id": cid,
    }


def _data_source_for(protocol: str) -> str:
    if protocol == "http":
        return "HTTP_CHECK"
    if protocol == "tcp":
        return "TCP_CHECK"
    if protocol == "icmp":
        return "ICMP_CHECK"
    if protocol == "snmp":
        return "SNMP"
    return "HTTP_CHECK"


def _link_check_to_target(*, tenant_id: str, target_id: str, check_id: str) -> None:
    tid = require_tenant_id(tenant_id)
    tid_target = str(target_id or "").strip()
    cid = str(check_id or "").strip()
    if not tid_target or not cid:
        return
    _targets().update_one(
        merge_tenant_filter({"target_id": tid_target}, tid),
        {
            "$addToSet": {"check_ids": cid},
            "$set": {"updated_at": _now()},
        },
    )


def rollup_target_status_from_checks(
    *,
    tenant_id: str,
    target_id: str,
) -> dict[str, Any] | None:
    """Roll target status / LIVE badges from recent agentless check results."""
    tid = require_tenant_id(tenant_id)
    tid_target = str(target_id or "").strip()
    if not tid_target:
        return None
    target = _targets().find_one(merge_tenant_filter({"target_id": tid_target}, tid))
    if target is None:
        return None

    checks = list(
        _checks().find(merge_tenant_filter({"target_id": tid_target}, tid))
    )
    check_ids = [str(c.get("check_id")) for c in checks if c.get("check_id")]
    live_results = [
        c.get("last_result")
        for c in checks
        if isinstance(c.get("last_result"), dict)
        and c["last_result"].get("execution_mode") == "LIVE"
    ]

    updates: dict[str, Any] = {
        "check_ids": check_ids,
        "updated_at": _now(),
    }

    if not live_results:
        # Keep SIMULATED status; still sync check_ids.
        _targets().update_one(
            merge_tenant_filter({"target_id": tid_target}, tid), {"$set": updates}
        )
        return _serialize(
            _targets().find_one(merge_tenant_filter({"target_id": tid_target}, tid))
        )

    oks = [bool(r.get("ok")) for r in live_results if not r.get("denied")]
    denied_only = all(bool(r.get("denied")) for r in live_results)
    skipped = any(
        "unavailable" in str(r.get("message") or "").lower()
        or "skipped" in str(r.get("message") or "").lower()
        for r in live_results
    )

    if denied_only or not oks:
        status = "unknown"
        reason = "all live checks denied or empty"
    elif all(oks):
        status = "healthy"
        reason = f"{len(oks)} live check(s) ok"
    elif any(oks):
        status = "degraded"
        reason = "mixed live check results"
    else:
        status = "down"
        reason = "all live checks failing"
    if skipped and status == "down":
        status = "degraded"
        reason = "icmp/snmp unavailable or failing (no crash)"

    # Prefer newest LIVE data_source among checks.
    data_source = "ICMP_CHECK"
    for c in checks:
        lr = c.get("last_result") or {}
        if lr.get("data_source"):
            data_source = str(lr["data_source"])
            break

    last_sample_at = None
    for r in live_results:
        obs = r.get("observed_at")
        if obs:
            last_sample_at = obs
            break

    updates.update(
        {
            "status": status,
            "execution_mode": "LIVE",
            "data_source": data_source,
            "live_status_reason": reason,
            "last_sample_at": last_sample_at or _now(),
        }
    )
    _targets().update_one(
        merge_tenant_filter({"target_id": tid_target}, tid), {"$set": updates}
    )
    return _serialize(
        _targets().find_one(merge_tenant_filter({"target_id": tid_target}, tid))
    )


def _persist_live_result(
    *,
    tenant_id: str,
    check: dict[str, Any],
    outcome: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    """Write LIVE result + metric sample when gates allow; always update last_*."""
    tid = require_tenant_id(tenant_id)
    now = _now()
    protocol = str(check.get("protocol") or "")
    data_source = _data_source_for(protocol)
    insecure = bool(
        outcome.get("secret_insecure_demo") or check.get("secret_insecure_demo")
    )
    result_summary = {
        "ok": bool(outcome.get("ok")),
        "latency_ms": outcome.get("latency_ms"),
        "value": outcome.get("value"),
        "message": outcome.get("message"),
        "denied": bool(outcome.get("denied")),
        "skipped": bool(outcome.get("skipped")),
        "secret_insecure_demo": insecure,
        "observed_at": now.isoformat(),
        "execution_mode": "LIVE",
        "data_source": data_source,
    }
    write_live = live_allowed(
        tenant_id=tid, capability="agentless_poll", settings=settings
    ) and not bool(outcome.get("denied"))

    result_doc: dict[str, Any] | None = None
    sample_doc: dict[str, Any] | None = None
    if write_live:
        result_doc = stamp_tenant_id(
            {
                "result_id": _new_result_id(),
                "check_id": check["check_id"],
                "ok": result_summary["ok"],
                "latency_ms": result_summary["latency_ms"],
                "value": result_summary["value"],
                "message": result_summary["message"],
                "observed_at": now,
                "execution_mode": "LIVE",
                "data_source": data_source,
                "protocol": protocol,
                "secret_insecure_demo": insecure,
                "created_at": now,
            },
            tenant_id=tid,
        )
        _results().insert_one(result_doc)

        metric_name = f"check.{protocol}.latency_ms"
        metric_value = outcome.get("latency_ms")
        # SNMP OID samples prefer the gauge/counter value when present.
        if protocol == "snmp" and outcome.get("value") is not None:
            metric_name = f"check.snmp.oid"
            metric_value = outcome.get("value")
        elif metric_value is None:
            metric_name = f"check.{protocol}.ok"
            metric_value = 1.0 if outcome.get("ok") else 0.0
        sample_doc = stamp_tenant_id(
            {
                "sample_id": _new_sample_id(),
                "target_id": check.get("target_id"),
                "component_id": check.get("component_id") or check.get("target_id"),
                "metric_name": metric_name,
                "value": float(metric_value),
                "unit": (
                    None
                    if protocol == "snmp" and metric_name.endswith(".oid")
                    else ("ms" if "latency" in metric_name else None)
                ),
                "observed_at": now,
                "data_source": data_source,
                "collect_mode": "AGENTLESS",
                "execution_mode": "LIVE",
                "check_id": check["check_id"],
                "created_at": now,
            },
            tenant_id=tid,
        )
        _samples().insert_one(sample_doc)
        try:
            from .targets import enforce_metric_samples_retention

            enforce_metric_samples_retention(tenant_id=tid)
        except Exception:  # noqa: BLE001 — retention must not fail the check
            pass

    _checks().update_one(
        merge_tenant_filter({"check_id": check["check_id"]}, tid),
        {
            "$set": {
                "last_run_at": now,
                "last_result": result_summary,
                "updated_at": now,
            }
        },
    )

    rolled = None
    if check.get("target_id"):
        try:
            rolled = rollup_target_status_from_checks(
                tenant_id=tid, target_id=str(check["target_id"])
            )
        except Exception:  # noqa: BLE001 — rollup must not fail the check
            rolled = None

    return {
        "check_id": check["check_id"],
        "ok": result_summary["ok"],
        "denied": bool(outcome.get("denied")),
        "skipped": bool(outcome.get("skipped")),
        "secret_insecure_demo": insecure,
        "latency_ms": result_summary["latency_ms"],
        "value": result_summary["value"],
        "message": result_summary["message"],
        "execution_mode": "LIVE" if write_live else None,
        "live_written": write_live,
        "result": _serialize(result_doc) if result_doc else None,
        "sample": _serialize(sample_doc) if sample_doc else None,
        "target": rolled,
        "observed_at": now.isoformat(),
    }


def run_check_once(
    *,
    tenant_id: str,
    check_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Execute one check behind agentless_poll gate + egress allowlist."""
    cfg = settings or get_settings()
    tid = require_tenant_id(tenant_id)
    if not live_allowed(tenant_id=tid, capability="agentless_poll", settings=cfg):
        raise MonitorChecksError(
            "Live monitoring is disabled (platform and/or tenant gate). "
            "SIMULATED paths remain available.",
            status_code=403,
        )
    check = _checks().find_one(
        merge_tenant_filter({"check_id": str(check_id).strip()}, tid)
    )
    if check is None:
        raise MonitorChecksError(f"Check '{check_id}' not found", status_code=404)

    outcome = executors.execute_check(
        protocol=str(check.get("protocol") or ""),
        endpoint=dict(check.get("endpoint") or {}),
        timeout_seconds=float(check.get("timeout_seconds") or DEFAULT_TIMEOUT),
        platform_allowlist=cfg.monitor_egress_allowlist or "",
        check_allowlist=list(check.get("egress_allowlist") or []),
        secret_ref=check.get("secret_ref"),
    )
    return _persist_live_result(
        tenant_id=tid, check=check, outcome=outcome, settings=cfg
    )


def due_checks_for_tenant(*, tenant_id: str, now: datetime | None = None) -> list[dict]:
    """Enabled checks whose interval has elapsed (or never run)."""
    tid = require_tenant_id(tenant_id)
    clock = now or _now()
    due: list[dict] = []
    for doc in _checks().find(merge_tenant_filter({"enabled": True}, tid)):
        interval = int(doc.get("interval_seconds") or DEFAULT_INTERVAL)
        last = doc.get("last_run_at")
        if last is None:
            due.append(doc)
            continue
        if getattr(last, "tzinfo", None) is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (clock - last).total_seconds()
        if elapsed >= interval:
            due.append(doc)
    return due


def run_due_checks_for_tenant(
    *,
    tenant_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run due checks for one tenant when agentless_poll is allowed."""
    cfg = settings or get_settings()
    tid = require_tenant_id(tenant_id)
    if not live_allowed(tenant_id=tid, capability="agentless_poll", settings=cfg):
        return {
            "tenant_id": tid,
            "skipped": True,
            "reason": "agentless_poll_gate_off",
            "ran": 0,
            "results": [],
        }
    due = due_checks_for_tenant(tenant_id=tid)
    results: list[dict[str, Any]] = []
    for check in due:
        try:
            outcome = executors.execute_check(
                protocol=str(check.get("protocol") or ""),
                endpoint=dict(check.get("endpoint") or {}),
                timeout_seconds=float(check.get("timeout_seconds") or DEFAULT_TIMEOUT),
                platform_allowlist=cfg.monitor_egress_allowlist or "",
                check_allowlist=list(check.get("egress_allowlist") or []),
                secret_ref=check.get("secret_ref"),
            )
        except Exception as exc:  # noqa: BLE001 — never crash the poller on one check
            outcome = {
                "ok": False,
                "latency_ms": None,
                "value": None,
                "message": f"executor crash guarded: {exc}",
                "denied": False,
            }
        results.append(
            _persist_live_result(
                tenant_id=tid, check=check, outcome=outcome, settings=cfg
            )
        )
    return {
        "tenant_id": tid,
        "skipped": False,
        "ran": len(results),
        "results": results,
    }
