"""SIMULATED alert rules + instances (tenant-scoped, monitor DB).

Evaluation runs against synthetic metrics / log events / file events only.
Never auto-creates ITSM incidents.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from ...serialization import serialize_document
from ...services import entitlements as entitlements_service
from ...services.entitlements import EntitlementError
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id, tenant_filter
from .indexes import ensure_monitor_indexes
from .meta import DATA_SOURCE, EXECUTION_MODE

RULES_COLLECTION = "alert_rules"
INSTANCES_COLLECTION = "alert_instances"

CONDITION_TYPES: tuple[str, ...] = ("threshold", "log_match", "file_change")
OPERATORS: tuple[str, ...] = ("gt", "gte", "lt", "lte", "eq")
SEVERITIES: tuple[str, ...] = ("info", "warning", "error", "critical")
ALERT_STATUSES: tuple[str, ...] = ("firing", "acked", "resolved")
OPEN_STATUSES: tuple[str, ...] = ("firing", "acked")
LOG_SEVERITIES: tuple[str, ...] = (
    "debug",
    "info",
    "warning",
    "error",
    "critical",
)

# Lookback for log_match / file_change evaluation windows.
EVAL_LOOKBACK = timedelta(minutes=30)


class MonitorAlertsError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_rule_id() -> str:
    return f"ar-{uuid.uuid4().hex[:12]}"


def _new_alert_id() -> str:
    return f"al-{uuid.uuid4().hex[:12]}"


def _rules() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[RULES_COLLECTION]


def _instances() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[INSTANCES_COLLECTION]


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    return serialize_document(doc)


def count_alert_rules(*, tenant_id: str) -> int:
    tid = require_tenant_id(tenant_id)
    return int(_rules().count_documents(tenant_filter(tid)))


def assert_can_create_alert_rule(tenant_id: str) -> None:
    """Enforce ``alert_rules`` entitlement before creating a new rule."""
    tid = require_tenant_id(tenant_id)
    limit = entitlements_service.alert_rules_limit(tid)
    if limit is None:
        return
    total = count_alert_rules(tenant_id=tid)
    if total >= limit:
        raise EntitlementError(
            f"Alert rule limit reached for this tenant "
            f"({total}/{limit}). Upgrade entitlements to create more rules.",
            status_code=403,
        )


def _normalize_scope(raw: dict[str, Any] | None) -> dict[str, Any]:
    scope = raw or {}
    out: dict[str, Any] = {}
    for key in ("domain", "component_id", "target_id", "stream_id", "watch_id"):
        val = scope.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            out[key] = text
    if out.get("domain"):
        domain = out["domain"].lower()
        if domain not in {
            "server",
            "network",
            "application",
            "database",
            "middleware",
        }:
            raise MonitorAlertsError(
                f"Invalid scope.domain '{out['domain']}'",
                status_code=422,
            )
        out["domain"] = domain
    return out


def _normalize_condition(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw or not isinstance(raw, dict):
        raise MonitorAlertsError("condition is required", status_code=422)
    ctype = str(raw.get("type") or "").strip().lower()
    if ctype not in CONDITION_TYPES:
        raise MonitorAlertsError(
            f"Invalid condition.type '{raw.get('type')}' "
            f"(expected one of: {', '.join(CONDITION_TYPES)})",
            status_code=422,
        )
    condition: dict[str, Any] = {"type": ctype}
    if ctype == "threshold":
        metric = str(raw.get("metric_name") or "").strip()
        if not metric:
            raise MonitorAlertsError(
                "threshold condition requires metric_name", status_code=422
            )
        op = str(raw.get("operator") or "gt").strip().lower()
        if op not in OPERATORS:
            raise MonitorAlertsError(
                f"Invalid operator '{raw.get('operator')}' "
                f"(expected one of: {', '.join(OPERATORS)})",
                status_code=422,
            )
        if raw.get("value") is None:
            raise MonitorAlertsError(
                "threshold condition requires value", status_code=422
            )
        try:
            value = float(raw["value"])
        except (TypeError, ValueError) as exc:
            raise MonitorAlertsError(
                "threshold value must be numeric", status_code=422
            ) from exc
        condition["metric_name"] = metric
        condition["operator"] = op
        condition["value"] = value
    elif ctype == "log_match":
        sev = raw.get("severity")
        msg = raw.get("message_contains")
        if not sev and not msg:
            raise MonitorAlertsError(
                "log_match requires severity and/or message_contains",
                status_code=422,
            )
        if sev is not None:
            parts = [
                p.strip().lower()
                for p in str(sev).split(",")
                if p.strip()
            ]
            bad = [p for p in parts if p not in LOG_SEVERITIES]
            if bad:
                raise MonitorAlertsError(
                    f"Invalid log severity '{sev}'",
                    status_code=422,
                )
            condition["severity"] = ",".join(parts)
        if msg is not None:
            text = str(msg).strip()
            if text:
                condition["message_contains"] = text
        if not condition.get("severity") and not condition.get("message_contains"):
            raise MonitorAlertsError(
                "log_match requires severity and/or message_contains",
                status_code=422,
            )
    else:  # file_change
        path = raw.get("path_contains")
        if path is not None:
            text = str(path).strip()
            if text:
                condition["path_contains"] = text
    return condition


def _normalize_severity(raw: str | None, *, default: str = "warning") -> str:
    sev = str(raw or default).strip().lower()
    if sev not in SEVERITIES:
        raise MonitorAlertsError(
            f"Invalid severity '{raw}' "
            f"(expected one of: {', '.join(SEVERITIES)})",
            status_code=422,
        )
    return sev


def _fingerprint(rule_id: str, *, component_id: str | None, key: str | None) -> str:
    cid = (component_id or "").strip() or "_"
    extra = (key or "").strip() or "_"
    return f"{rule_id}:{cid}:{extra}"


def _compare(op: str, left: float, right: float) -> bool:
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    return left == right


def ensure_default_rules(*, tenant_id: str) -> list[dict[str, Any]]:
    """Seed a small set of SIMULATED demo rules when the tenant has none."""
    tid = require_tenant_id(tenant_id)
    coll = _rules()
    existing = list(coll.find(tenant_filter(tid)).sort([("name", ASCENDING)]))
    if existing:
        return [_serialize(doc) for doc in existing]  # type: ignore[misc]

    now = _now()
    demos = [
        {
            "name": "SIMULATED high CPU",
            "enabled": True,
            "scope": {},
            "condition": {
                "type": "threshold",
                "metric_name": "cpu_pct",
                "operator": "gt",
                "value": 50.0,
            },
            "severity": "warning",
            "description": "Demo threshold on synthetic cpu_pct samples.",
        },
        {
            "name": "SIMULATED error / critical logs",
            "enabled": True,
            "scope": {},
            "condition": {
                "type": "log_match",
                "severity": "error,critical",
            },
            "severity": "error",
            "description": "Demo log match on synthetic error/critical events.",
        },
        {
            "name": "SIMULATED file change",
            "enabled": True,
            "scope": {},
            "condition": {"type": "file_change"},
            "severity": "info",
            "description": "Demo rule for synthetic file version events.",
        },
    ]
    created: list[dict[str, Any]] = []
    for idx, spec in enumerate(demos):
        try:
            assert_can_create_alert_rule(tid)
        except EntitlementError:
            break
        doc = stamp_tenant_id(
            {
                "rule_id": _new_rule_id(),
                "name": spec["name"],
                "enabled": True,
                "scope": spec["scope"],
                "condition": spec["condition"],
                "severity": spec["severity"],
                "description": spec["description"],
                "execution_mode": EXECUTION_MODE,
                "data_source": DATA_SOURCE,
                "created_at": now + timedelta(milliseconds=idx),
                "updated_at": now + timedelta(milliseconds=idx),
            },
            tenant_id=tid,
        )
        coll.insert_one(doc)
        created.append(doc)
    return [_serialize(doc) for doc in created]  # type: ignore[misc]


def list_rules(
    *,
    tenant_id: str,
    q: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    ensure_default_rules(tenant_id=tid)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    query: dict[str, Any] = {}
    if enabled is not None:
        query["enabled"] = bool(enabled)
    if q:
        term = q.strip()
        if term:
            query["$or"] = [
                {"name": {"$regex": term, "$options": "i"}},
                {"rule_id": {"$regex": term, "$options": "i"}},
                {"description": {"$regex": term, "$options": "i"}},
            ]
    filt = merge_tenant_filter(query, tid)
    coll = _rules()
    total = coll.count_documents(filt)
    cursor = (
        coll.find(filt)
        .sort([("name", ASCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [_serialize(doc) for doc in cursor]
    limit = entitlements_service.alert_rules_limit(tid)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "items": items,
        "tenant_id": tid,
        "rules_limit": limit,
        "execution_mode": EXECUTION_MODE,
        "live_probes": False,
    }


def get_rule(*, tenant_id: str, rule_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _rules().find_one(
        merge_tenant_filter({"rule_id": rule_id.strip()}, tid)
    )
    return _serialize(doc)


def create_rule(
    *,
    tenant_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    assert_can_create_alert_rule(tid)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise MonitorAlertsError("name is required", status_code=422)
    scope = _normalize_scope(payload.get("scope"))
    condition = _normalize_condition(payload.get("condition"))
    severity = _normalize_severity(payload.get("severity"))
    enabled = bool(payload.get("enabled", True))
    description = payload.get("description")
    if description is not None:
        description = str(description).strip() or None
    auto_incident = bool(payload.get("auto_incident", False))
    now = _now()
    doc = stamp_tenant_id(
        {
            "rule_id": _new_rule_id(),
            "name": name,
            "enabled": enabled,
            "scope": scope,
            "condition": condition,
            "severity": severity,
            "description": description,
            "auto_incident": auto_incident,
            "execution_mode": EXECUTION_MODE,
            "data_source": DATA_SOURCE,
            "created_at": now,
            "updated_at": now,
        },
        tenant_id=tid,
    )
    _rules().insert_one(doc)
    return _serialize(doc)  # type: ignore[return-value]


def patch_rule(
    *,
    tenant_id: str,
    rule_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    rid = rule_id.strip()
    coll = _rules()
    existing = coll.find_one(merge_tenant_filter({"rule_id": rid}, tid))
    if not existing:
        raise MonitorAlertsError(f"Rule '{rid}' not found", status_code=404)
    updates: dict[str, Any] = {}
    if "name" in payload and payload["name"] is not None:
        name = str(payload["name"]).strip()
        if not name:
            raise MonitorAlertsError("name cannot be empty", status_code=422)
        updates["name"] = name
    if "enabled" in payload and payload["enabled"] is not None:
        updates["enabled"] = bool(payload["enabled"])
    if "scope" in payload and payload["scope"] is not None:
        updates["scope"] = _normalize_scope(payload["scope"])
    if "condition" in payload and payload["condition"] is not None:
        updates["condition"] = _normalize_condition(payload["condition"])
    if "severity" in payload and payload["severity"] is not None:
        updates["severity"] = _normalize_severity(payload["severity"])
    if "description" in payload:
        desc = payload["description"]
        updates["description"] = (
            None if desc is None else (str(desc).strip() or None)
        )
    if "auto_incident" in payload and payload["auto_incident"] is not None:
        updates["auto_incident"] = bool(payload["auto_incident"])
    if not updates:
        return _serialize(existing)  # type: ignore[return-value]
    updates["updated_at"] = _now()
    coll.update_one(
        merge_tenant_filter({"rule_id": rid}, tid),
        {"$set": updates},
    )
    return get_rule(tenant_id=tid, rule_id=rid)  # type: ignore[return-value]


def delete_rule(*, tenant_id: str, rule_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    rid = rule_id.strip()
    result = _rules().delete_one(merge_tenant_filter({"rule_id": rid}, tid))
    if result.deleted_count == 0:
        raise MonitorAlertsError(f"Rule '{rid}' not found", status_code=404)
    return {"ok": True, "rule_id": rid, "deleted": True}


def list_instances(
    *,
    tenant_id: str,
    status: str | None = None,
    rule_id: str | None = None,
    component_id: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    query: dict[str, Any] = {}
    if status:
        parts = [p.strip().lower() for p in status.split(",") if p.strip()]
        bad = [p for p in parts if p not in ALERT_STATUSES]
        if bad:
            raise MonitorAlertsError(
                f"Invalid status '{status}' "
                f"(expected one of: {', '.join(ALERT_STATUSES)})",
                status_code=422,
            )
        if len(parts) == 1:
            query["status"] = parts[0]
        elif parts:
            query["status"] = {"$in": parts}
    if rule_id:
        query["rule_id"] = rule_id.strip()
    if component_id:
        query["component_id"] = component_id.strip()
    if q:
        term = q.strip()
        if term:
            query["$or"] = [
                {"summary": {"$regex": term, "$options": "i"}},
                {"alert_id": {"$regex": term, "$options": "i"}},
                {"rule_name": {"$regex": term, "$options": "i"}},
                {"component_id": {"$regex": term, "$options": "i"}},
            ]
    filt = merge_tenant_filter(query, tid)
    coll = _instances()
    total = coll.count_documents(filt)
    cursor = (
        coll.find(filt)
        .sort([("fired_at", DESCENDING), ("alert_id", DESCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [_serialize(doc) for doc in cursor]
    open_count = coll.count_documents(
        merge_tenant_filter({"status": {"$in": list(OPEN_STATUSES)}}, tid)
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "items": items,
        "open_count": open_count,
        "tenant_id": tid,
        "execution_mode": EXECUTION_MODE,
        "live_probes": False,
        "filters": {
            "status": status,
            "rule_id": rule_id,
            "component_id": component_id,
            "q": q,
        },
    }


def get_instance(*, tenant_id: str, alert_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _instances().find_one(
        merge_tenant_filter({"alert_id": alert_id.strip()}, tid)
    )
    return _serialize(doc)


def ack_instance(
    *,
    tenant_id: str,
    alert_id: str,
    actor: str | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    aid = alert_id.strip()
    coll = _instances()
    doc = coll.find_one(merge_tenant_filter({"alert_id": aid}, tid))
    if not doc:
        raise MonitorAlertsError(f"Alert '{aid}' not found", status_code=404)
    if doc.get("status") == "resolved":
        raise MonitorAlertsError(
            "Resolved alerts cannot be acknowledged", status_code=409
        )
    if doc.get("status") == "acked":
        return _serialize(doc)  # type: ignore[return-value]
    now = _now()
    coll.update_one(
        merge_tenant_filter({"alert_id": aid}, tid),
        {
            "$set": {
                "status": "acked",
                "acked_at": now,
                "acked_by": actor,
                "updated_at": now,
            }
        },
    )
    return get_instance(tenant_id=tid, alert_id=aid)  # type: ignore[return-value]


def resolve_instance(
    *,
    tenant_id: str,
    alert_id: str,
    actor: str | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    aid = alert_id.strip()
    coll = _instances()
    doc = coll.find_one(merge_tenant_filter({"alert_id": aid}, tid))
    if not doc:
        raise MonitorAlertsError(f"Alert '{aid}' not found", status_code=404)
    if doc.get("status") == "resolved":
        return _serialize(doc)  # type: ignore[return-value]
    now = _now()
    updates: dict[str, Any] = {
        "status": "resolved",
        "resolved_at": now,
        "resolved_by": actor,
        "updated_at": now,
    }
    if doc.get("status") == "firing" and not doc.get("acked_at"):
        updates["acked_at"] = now
        updates["acked_by"] = actor
    coll.update_one(
        merge_tenant_filter({"alert_id": aid}, tid),
        {"$set": updates},
    )
    return get_instance(tenant_id=tid, alert_id=aid)  # type: ignore[return-value]


def suggest_incident(*, tenant_id: str, alert_id: str) -> dict[str, Any]:
    """Build an ITSM incident **draft** from alert evidence (no ITSM write)."""
    from . import itsm_client

    tid = require_tenant_id(tenant_id)
    aid = alert_id.strip()
    doc = get_instance(tenant_id=tid, alert_id=aid)
    if doc is None:
        raise MonitorAlertsError(f"Alert '{aid}' not found", status_code=404)
    draft = itsm_client.draft_incident_from_alert(doc)
    return {
        "alert": {
            "alert_id": doc.get("alert_id"),
            "rule_id": doc.get("rule_id"),
            "rule_name": doc.get("rule_name"),
            "status": doc.get("status"),
            "severity": doc.get("severity"),
            "summary": doc.get("summary"),
            "component_id": doc.get("component_id"),
            "suggested_incident_id": doc.get("suggested_incident_id"),
        },
        "draft": draft,
        "source": draft.get("source") or "rule_based_fallback",
        "auto_create": False,
        "execution_mode": EXECUTION_MODE,
        "live_probes": False,
        "tenant_id": tid,
    }


def link_suggested_incident(
    *,
    tenant_id: str,
    alert_id: str,
    incident_id: str,
) -> dict[str, Any]:
    """Stamp ``suggested_incident_id`` after a human created the ITSM incident.

    Updates Monitoring only — never writes ITSM collections.
    """
    tid = require_tenant_id(tenant_id)
    aid = alert_id.strip()
    iid = (incident_id or "").strip()
    if not iid:
        raise MonitorAlertsError("incident_id is required", status_code=422)
    coll = _instances()
    doc = coll.find_one(merge_tenant_filter({"alert_id": aid}, tid))
    if not doc:
        raise MonitorAlertsError(f"Alert '{aid}' not found", status_code=404)
    now = _now()
    coll.update_one(
        merge_tenant_filter({"alert_id": aid}, tid),
        {
            "$set": {
                "suggested_incident_id": iid[:128],
                "updated_at": now,
            }
        },
    )
    return get_instance(tenant_id=tid, alert_id=aid)  # type: ignore[return-value]


def _has_open_fingerprint(*, tenant_id: str, fingerprint: str) -> bool:
    tid = require_tenant_id(tenant_id)
    doc = _instances().find_one(
        merge_tenant_filter(
            {
                "fingerprint": fingerprint,
                "status": {"$in": list(OPEN_STATUSES)},
            },
            tid,
        )
    )
    return doc is not None


def _create_instance(
    *,
    tenant_id: str,
    rule: dict[str, Any],
    summary: str,
    component_id: str | None = None,
    target_id: str | None = None,
    stream_id: str | None = None,
    watch_id: str | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
    fingerprint_key: str | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    """Return ``(doc_or_none, skipped_open)``."""
    tid = require_tenant_id(tenant_id)
    fp = _fingerprint(
        rule["rule_id"],
        component_id=component_id,
        key=fingerprint_key or target_id or stream_id or watch_id,
    )
    if _has_open_fingerprint(tenant_id=tid, fingerprint=fp):
        return None, True
    now = _now()
    doc = stamp_tenant_id(
        {
            "alert_id": _new_alert_id(),
            "rule_id": rule["rule_id"],
            "rule_name": rule.get("name"),
            "component_id": component_id,
            "target_id": target_id,
            "stream_id": stream_id,
            "watch_id": watch_id,
            "fingerprint": fp,
            "status": "firing",
            "severity": rule.get("severity") or "warning",
            "summary": summary,
            "evidence_refs": evidence_refs or [],
            "suggested_incident_id": None,
            "fired_at": now,
            "acked_at": None,
            "resolved_at": None,
            "acked_by": None,
            "resolved_by": None,
            "execution_mode": EXECUTION_MODE,
            "data_source": DATA_SOURCE,
            "created_at": now,
            "updated_at": now,
        },
        tenant_id=tid,
    )
    _instances().insert_one(doc)
    return doc, False


def _scope_filter(scope: dict[str, Any]) -> dict[str, Any]:
    query: dict[str, Any] = {}
    for key in ("component_id", "target_id", "stream_id", "watch_id", "domain"):
        if scope.get(key):
            query[key] = scope[key]
    return query


def _eval_threshold(
    *,
    tenant_id: str,
    rule: dict[str, Any],
) -> list[dict[str, Any]]:
    from ...db import require_monitor_database

    tid = require_tenant_id(tenant_id)
    condition = rule.get("condition") or {}
    scope = rule.get("scope") or {}
    metric_name = condition.get("metric_name")
    op = condition.get("operator") or "gt"
    threshold = float(condition.get("value"))
    db = require_monitor_database()
    query = _scope_filter(scope)
    query["metric_name"] = metric_name
    filt = merge_tenant_filter(query, tid)
    # Latest sample per target for this metric.
    pipeline = [
        {"$match": filt},
        {"$sort": {"observed_at": DESCENDING}},
        {
            "$group": {
                "_id": "$target_id",
                "sample_id": {"$first": "$sample_id"},
                "component_id": {"$first": "$component_id"},
                "target_id": {"$first": "$target_id"},
                "value": {"$first": "$value"},
                "unit": {"$first": "$unit"},
                "observed_at": {"$first": "$observed_at"},
                "metric_name": {"$first": "$metric_name"},
            }
        },
    ]
    created: list[dict[str, Any]] = []
    for row in db["metric_samples"].aggregate(pipeline):
        value = float(row.get("value") or 0)
        if not _compare(op, value, threshold):
            continue
        unit = row.get("unit") or ""
        summary = (
            f"{metric_name} {op} {threshold}{unit} "
            f"(observed {value}{unit})"
        )
        doc, _skipped = _create_instance(
            tenant_id=tid,
            rule=rule,
            summary=summary,
            component_id=row.get("component_id"),
            target_id=row.get("target_id"),
            evidence_refs=[
                {
                    "kind": "metric_sample",
                    "sample_id": row.get("sample_id"),
                    "metric_name": metric_name,
                    "value": value,
                    "threshold": threshold,
                    "operator": op,
                    "observed_at": row.get("observed_at"),
                }
            ],
            fingerprint_key=f"{metric_name}:{row.get('target_id')}",
        )
        if doc:
            created.append(doc)
    return created


def _eval_log_match(
    *,
    tenant_id: str,
    rule: dict[str, Any],
) -> list[dict[str, Any]]:
    from ...db import require_monitor_database

    tid = require_tenant_id(tenant_id)
    condition = rule.get("condition") or {}
    scope = rule.get("scope") or {}
    query = _scope_filter(
        {k: v for k, v in scope.items() if k != "domain"}
    )
    since = _now() - EVAL_LOOKBACK
    query["observed_at"] = {"$gte": since}
    sev = condition.get("severity")
    if sev:
        parts = [p.strip() for p in str(sev).split(",") if p.strip()]
        if len(parts) == 1:
            query["severity"] = parts[0]
        else:
            query["severity"] = {"$in": parts}
    msg = condition.get("message_contains")
    if msg:
        query["message"] = {"$regex": str(msg), "$options": "i"}
    # Optional domain scope via target join is skipped; component_id on events is enough.
    filt = merge_tenant_filter(query, tid)
    events = list(
        require_monitor_database()["log_events"]
        .find(filt)
        .sort([("observed_at", DESCENDING)])
        .limit(50)
    )
    created: list[dict[str, Any]] = []
    # Group by component/stream so one open alert covers the match set.
    seen_keys: set[str] = set()
    for event in events:
        key = (
            f"{event.get('component_id') or '_'}:"
            f"{event.get('stream_id') or '_'}"
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        summary = (
            f"Log match: [{event.get('severity')}] "
            f"{(event.get('message') or '')[:120]}"
        )
        doc, _skipped = _create_instance(
            tenant_id=tid,
            rule=rule,
            summary=summary,
            component_id=event.get("component_id"),
            target_id=event.get("target_id"),
            stream_id=event.get("stream_id"),
            evidence_refs=[
                {
                    "kind": "log_event",
                    "event_id": event.get("event_id"),
                    "stream_id": event.get("stream_id"),
                    "severity": event.get("severity"),
                    "message": event.get("message"),
                    "observed_at": event.get("observed_at"),
                }
            ],
            fingerprint_key=event.get("stream_id"),
        )
        if doc:
            created.append(doc)
    return created


def _eval_file_change(
    *,
    tenant_id: str,
    rule: dict[str, Any],
) -> list[dict[str, Any]]:
    from ...db import require_monitor_database

    tid = require_tenant_id(tenant_id)
    condition = rule.get("condition") or {}
    scope = rule.get("scope") or {}
    query: dict[str, Any] = {"changed_at": {"$gte": _now() - EVAL_LOOKBACK}}
    if scope.get("watch_id"):
        query["watch_id"] = scope["watch_id"]
    if scope.get("component_id"):
        query["component_id"] = scope["component_id"]
    path = condition.get("path_contains")
    if path:
        query["path"] = {"$regex": str(path), "$options": "i"}
    filt = merge_tenant_filter(query, tid)
    events = list(
        require_monitor_database()["file_version_events"]
        .find(filt)
        .sort([("changed_at", DESCENDING)])
        .limit(50)
    )
    created: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        wid = str(event.get("watch_id") or event.get("path") or "_")
        if wid in seen:
            continue
        seen.add(wid)
        path_val = event.get("path") or event.get("watch_id") or "file"
        summary = f"File change: {path_val} (v{event.get('version', '?')})"
        doc, _skipped = _create_instance(
            tenant_id=tid,
            rule=rule,
            summary=summary,
            component_id=event.get("component_id"),
            watch_id=event.get("watch_id"),
            evidence_refs=[
                {
                    "kind": "file_version_event",
                    "event_id": event.get("event_id"),
                    "watch_id": event.get("watch_id"),
                    "path": event.get("path"),
                    "version": event.get("version"),
                    "changed_at": event.get("changed_at"),
                }
            ],
            fingerprint_key=event.get("watch_id") or event.get("path"),
        )
        if doc:
            created.append(doc)
    return created


def evaluate_rules(*, tenant_id: str) -> dict[str, Any]:
    """Run enabled rules against SIMULATED telemetry. No ITSM side effects."""
    tid = require_tenant_id(tenant_id)
    ensure_default_rules(tenant_id=tid)
    rules = list(
        _rules().find(merge_tenant_filter({"enabled": True}, tid))
    )
    created_total = 0
    matches = 0
    for rule in rules:
        ctype = (rule.get("condition") or {}).get("type")
        if ctype == "threshold":
            made = _eval_threshold(tenant_id=tid, rule=rule)
        elif ctype == "log_match":
            made = _eval_log_match(tenant_id=tid, rule=rule)
        elif ctype == "file_change":
            made = _eval_file_change(tenant_id=tid, rule=rule)
        else:
            continue
        created_total += len(made)
        matches += len(made)
    open_count = _instances().count_documents(
        merge_tenant_filter({"status": {"$in": list(OPEN_STATUSES)}}, tid)
    )
    return {
        "tenant_id": tid,
        "rules_evaluated": len(rules),
        "matches": matches,
        "created": created_total,
        "open_count": open_count,
        "execution_mode": EXECUTION_MODE,
        "live_probes": False,
        "data_source": DATA_SOURCE,
    }
