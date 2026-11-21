"""Monitoring targets + SIMULATED metric samples (tenant-scoped, monitor DB).

Targets are upserted from CMDB via ``cmdb_client`` (API/service boundary — no
cross-DB joins). Execution stays SIMULATED; ``collect_mode`` is always stamped
AGENTLESS or AGENT even when live probes are off.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from ...serialization import serialize_document
from ...services import entitlements as entitlements_service
from ...services.entitlements import EntitlementError
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id, tenant_filter
from . import cmdb_client
from .indexes import ensure_monitor_indexes
from .meta import (
    COLLECT_MODES,
    DATA_SOURCE,
    DOMAINS,
    EXECUTION_MODE,
    NETWORK_TARGET_KINDS,
    OS_FAMILIES,
)

TARGETS_COLLECTION = "monitor_targets"
SAMPLES_COLLECTION = "metric_samples"

TARGET_STATUSES: tuple[str, ...] = (
    "unknown",
    "healthy",
    "degraded",
    "down",
    "maintenance",
)

# Preferred collect mode by domain when hashing is not used for demo diversity.
_DOMAIN_COLLECT_HINT: dict[str, str] = {
    "server": "AGENT",
    "network": "AGENTLESS",
    "application": "AGENTLESS",
    "database": "AGENT",
}

_NETWORK_KIND_ALIASES: dict[str, str] = {
    "switch": "switch",
    "l2_switch": "switch",
    "l3_switch": "switch",
    "router": "router",
    "firewall": "firewall",
    "ngfw": "firewall",
    "load_balancer": "load_balancer",
    "loadbalancer": "load_balancer",
    "lb": "load_balancer",
    "adc": "load_balancer",
    "access_point": "access_point",
    "accesspoint": "access_point",
    "ap": "access_point",
    "wireless": "access_point",
    "wifi": "access_point",
    "wifi_ap": "access_point",
    "other": "other_network",
    "other_network": "other_network",
}

_OS_FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
    ("windows", "windows"),
    ("win", "windows"),
    ("macos", "macos"),
    ("mac os", "macos"),
    ("darwin", "macos"),
    ("aix", "unix"),
    ("solaris", "unix"),
    ("sunos", "unix"),
    ("bsd", "unix"),
    ("hp-ux", "unix"),
    ("hpux", "unix"),
    ("unix", "unix"),
    ("linux", "linux"),
    ("rhel", "linux"),
    ("redhat", "linux"),
    ("ubuntu", "linux"),
    ("debian", "linux"),
    ("centos", "linux"),
    ("rocky", "linux"),
    ("alma", "linux"),
    ("suse", "linux"),
    ("fedora", "linux"),
    ("amazon", "linux"),
)


class MonitorTargetsError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_target_id() -> str:
    return f"mt-{uuid.uuid4().hex[:12]}"


def _new_sample_id() -> str:
    return f"ms-{uuid.uuid4().hex[:12]}"


def _targets() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[TARGETS_COLLECTION]


def _samples() -> Collection:
    ensure_monitor_indexes()
    from ...db import require_monitor_database

    return require_monitor_database()[SAMPLES_COLLECTION]


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    return serialize_document(doc)


def normalize_os_family(raw: str | None) -> str | None:
    """Map CMDB os_family / os_name snapshots onto taxonomy families."""
    text = (raw or "").strip().lower()
    if not text:
        return None
    if text in OS_FAMILIES:
        return text
    for needle, family in _OS_FAMILY_PATTERNS:
        if needle in text:
            return family
    return None


def normalize_network_kind(raw: str | None) -> str:
    """Map CMDB device_type onto first-class network target kinds."""
    key = re.sub(r"[\s\-]+", "_", (raw or "").strip().lower())
    if not key:
        return "other_network"
    if key in NETWORK_TARGET_KINDS:
        return key
    if key in _NETWORK_KIND_ALIASES:
        return _NETWORK_KIND_ALIASES[key]
    for needle, mapped in _NETWORK_KIND_ALIASES.items():
        if needle and needle in key:
            return mapped
    return "other_network"


def _stable_bucket(seed: str, modulus: int) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % max(1, modulus)


def _preferred_collect_mode(domain: str, component_id: str) -> str:
    """Stamp AGENTLESS or AGENT — both appear in demo data."""
    hint = _DOMAIN_COLLECT_HINT.get(domain, "AGENTLESS")
    # Flip ~40% of targets off the domain hint so both modes show per domain.
    if _stable_bucket(f"collect:{component_id}", 5) < 2:
        return "AGENT" if hint == "AGENTLESS" else "AGENTLESS"
    return hint


def _simulated_status(component_id: str, ci_status: str | None) -> str:
    if (ci_status or "").strip().lower() in {"inactive", "decommissioned"}:
        return "maintenance"
    bucket = _stable_bucket(f"status:{component_id}", 10)
    if bucket <= 5:
        return "healthy"
    if bucket <= 7:
        return "degraded"
    if bucket == 8:
        return "down"
    return "unknown"


def _target_kind_for_ci(domain: str, ci: dict[str, Any]) -> str | None:
    if domain == "network":
        return normalize_network_kind(ci.get("device_type") or ci.get("device_name"))
    if domain == "application":
        return (ci.get("application_type") or "application").strip() or "application"
    if domain == "database":
        return (ci.get("product_type") or "database").strip() or "database"
    if domain == "server":
        family = normalize_os_family(ci.get("os_family"))
        return family or "host"
    return None


def _name_snapshot(ci: dict[str, Any]) -> str:
    return (
        str(ci.get("name") or "").strip()
        or str(ci.get("hostname") or "").strip()
        or str(ci.get("device_name") or "").strip()
        or str(ci.get("application_name") or "").strip()
        or str(ci.get("component_id") or "").strip()
    )


def build_target_from_ci(ci: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
    """Project a CMDB CI into a monitor_targets document (no Mongo write)."""
    tid = require_tenant_id(tenant_id)
    cid = str(ci.get("component_id") or "").strip()
    if not cid:
        raise MonitorTargetsError("component_id is required", status_code=422)
    domain = cmdb_client.domain_for_component_type(ci.get("component_type"))
    if domain is None:
        raise MonitorTargetsError(
            f"Component '{cid}' type is not monitorable in v1",
            status_code=422,
        )
    os_name = (ci.get("os_family") or None) if domain == "server" else None
    os_family = normalize_os_family(os_name) if domain == "server" else None
    collect_mode = _preferred_collect_mode(domain, cid)
    now = _now()
    doc = {
        "target_id": _new_target_id(),
        "component_id": cid,
        "component_type": ci.get("component_type"),
        "name_snapshot": _name_snapshot(ci),
        "domain": domain,
        "target_kind": _target_kind_for_ci(domain, ci),
        "os_family": os_family,
        "os_name": os_name,
        "os_version": ci.get("os_version") if domain == "server" else None,
        "collect_mode": collect_mode,
        "status": _simulated_status(cid, ci.get("status")),
        "last_sample_at": None,
        "execution_mode": EXECUTION_MODE,
        "data_source": DATA_SOURCE,
        "created_at": now,
        "updated_at": now,
    }
    return stamp_tenant_id(doc, tenant_id=tid)


def _metric_specs(domain: str) -> list[tuple[str, str, float, float]]:
    """Return (metric_name, unit, base, jitter) specs per domain."""
    if domain == "server":
        return [
            ("cpu_pct", "%", 35.0, 40.0),
            ("mem_pct", "%", 55.0, 30.0),
            ("disk_pct", "%", 48.0, 25.0),
        ]
    if domain == "network":
        return [
            ("if_util_pct", "%", 22.0, 50.0),
            ("error_rate_pct", "%", 0.2, 1.5),
            ("latency_ms", "ms", 4.0, 12.0),
        ]
    if domain == "application":
        return [
            ("req_rate_rps", "rps", 120.0, 80.0),
            ("error_rate_pct", "%", 0.5, 2.0),
            ("p95_latency_ms", "ms", 85.0, 60.0),
        ]
    # database
    return [
        ("connections", "count", 40.0, 30.0),
        ("query_latency_ms", "ms", 12.0, 20.0),
        ("storage_pct", "%", 62.0, 20.0),
    ]


def _seed_samples_for_target(
    target: dict[str, Any], *, tenant_id: str, count_per_metric: int = 3
) -> int:
    """Write a few SIMULATED metric samples for both collect-mode labeling."""
    tid = require_tenant_id(tenant_id)
    coll = _samples()
    now = _now()
    inserted = 0
    domain = str(target.get("domain") or "server")
    collect_mode = str(target.get("collect_mode") or "AGENTLESS")
    for metric_name, unit, base, jitter in _metric_specs(domain):
        for i in range(count_per_metric):
            observed = now - timedelta(minutes=5 * (count_per_metric - i))
            frac = _stable_bucket(
                f"{target['target_id']}:{metric_name}:{i}", 1000
            ) / 1000.0
            value = round(base + jitter * frac, 3)
            doc = stamp_tenant_id(
                {
                    "sample_id": _new_sample_id(),
                    "target_id": target["target_id"],
                    "component_id": target["component_id"],
                    "metric_name": metric_name,
                    "value": value,
                    "unit": unit,
                    "observed_at": observed,
                    "data_source": DATA_SOURCE,
                    "collect_mode": collect_mode,
                    "execution_mode": EXECUTION_MODE,
                    "created_at": now,
                },
                tenant_id=tid,
            )
            coll.insert_one(doc)
            inserted += 1
    return inserted


def count_targets(*, tenant_id: str) -> int:
    tid = require_tenant_id(tenant_id)
    return int(_targets().count_documents(tenant_filter(tid)))


def count_metric_samples(*, tenant_id: str) -> int:
    tid = require_tenant_id(tenant_id)
    return int(_samples().count_documents(tenant_filter(tid)))


def enforce_metric_samples_retention(*, tenant_id: str) -> int:
    """Trim oldest metric samples when over ``metric_samples_retained``."""
    tid = require_tenant_id(tenant_id)
    limit = entitlements_service.metric_samples_retained_limit(tid)
    if limit is None:
        return 0
    coll = _samples()
    total = coll.count_documents(tenant_filter(tid))
    if total <= limit:
        return 0
    excess = total - limit
    oldest = list(
        coll.find(tenant_filter(tid), {"_id": 1})
        .sort([("observed_at", ASCENDING), ("_id", ASCENDING)])
        .limit(excess)
    )
    if not oldest:
        return 0
    ids = [row["_id"] for row in oldest]
    result = coll.delete_many({"_id": {"$in": ids}})
    return int(result.deleted_count)


def assert_can_create_monitor_target(tenant_id: str) -> None:
    """Enforce ``monitor_targets`` entitlement before creating a new target."""
    tid = require_tenant_id(tenant_id)
    limit = entitlements_service.monitor_target_limit(tid)
    if limit is None:
        return
    total = count_targets(tenant_id=tid)
    if total >= limit:
        raise EntitlementError(
            f"Monitoring target limit reached for this tenant "
            f"({total}/{limit}). Upgrade entitlements to sync more targets.",
            status_code=403,
        )


def sync_from_cmdb(*, tenant_id: str) -> dict[str, Any]:
    """Upsert monitor_targets from same-tenant CMDB CIs via service client.

    Existing targets are refreshed from CI snapshots. New targets respect the
    ``monitor_targets`` entitlement ceiling (partial sync when truncated).
    Seeds SIMULATED metric samples for newly created targets only.
    """
    tid = require_tenant_id(tenant_id)
    cis = cmdb_client.list_monitorable_components(tenant_id=tid)
    coll = _targets()
    created = 0
    updated = 0
    skipped = 0
    samples_seeded = 0
    entitlement_truncated = False
    domains: dict[str, int] = {d: 0 for d in DOMAINS}
    collect_modes: dict[str, int] = {m.upper(): 0 for m in COLLECT_MODES}
    limit = entitlements_service.monitor_target_limit(tid)

    for ci in cis:
        cid = str(ci.get("component_id") or "").strip()
        if not cid:
            skipped += 1
            continue
        domain = cmdb_client.domain_for_component_type(ci.get("component_type"))
        if domain is None:
            skipped += 1
            continue

        existing = coll.find_one(
            merge_tenant_filter({"component_id": cid}, tid)
        )
        now = _now()
        if existing:
            patch = {
                "component_type": ci.get("component_type"),
                "name_snapshot": _name_snapshot(ci),
                "domain": domain,
                "target_kind": _target_kind_for_ci(domain, ci),
                "os_family": normalize_os_family(ci.get("os_family"))
                if domain == "server"
                else None,
                "os_name": (ci.get("os_family") or None) if domain == "server" else None,
                "os_version": ci.get("os_version") if domain == "server" else None,
                # Preserve preferred collect_mode + SIMULATED status once set.
                "updated_at": now,
                "execution_mode": EXECUTION_MODE,
                "data_source": DATA_SOURCE,
            }
            coll.update_one(
                merge_tenant_filter({"target_id": existing["target_id"]}, tid),
                {"$set": patch},
            )
            updated += 1
            refreshed = {**existing, **patch}
            domains[domain] = domains.get(domain, 0) + 1
            mode = str(refreshed.get("collect_mode") or "AGENTLESS").upper()
            collect_modes[mode] = collect_modes.get(mode, 0) + 1
            continue

        try:
            assert_can_create_monitor_target(tid)
        except EntitlementError:
            entitlement_truncated = True
            skipped += 1
            continue

        doc = build_target_from_ci(ci, tenant_id=tid)
        coll.insert_one(doc)
        created += 1
        seeded = _seed_samples_for_target(doc, tenant_id=tid)
        samples_seeded += seeded
        if seeded:
            coll.update_one(
                merge_tenant_filter({"target_id": doc["target_id"]}, tid),
                {"$set": {"last_sample_at": _now(), "updated_at": _now()}},
            )
        domains[domain] = domains.get(domain, 0) + 1
        mode = str(doc.get("collect_mode") or "AGENTLESS").upper()
        collect_modes[mode] = collect_modes.get(mode, 0) + 1

    samples_trimmed = enforce_metric_samples_retention(tenant_id=tid)

    return {
        "tenant_id": tid,
        "scanned": len(cis),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "samples_seeded": samples_seeded,
        "samples_trimmed": samples_trimmed,
        "entitlement_limit": limit,
        "entitlement_truncated": entitlement_truncated,
        "domains": domains,
        "collect_modes": collect_modes,
        "execution_mode": EXECUTION_MODE,
        "live_probes": False,
        "total": count_targets(tenant_id=tid),
    }


def list_targets(
    *,
    tenant_id: str,
    q: str | None = None,
    domain: str | None = None,
    target_kind: str | None = None,
    os_family: str | None = None,
    collect_mode: str | None = None,
    status: str | None = None,
    component_id: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    allowed_sort = {
        "target_id",
        "component_id",
        "name_snapshot",
        "domain",
        "target_kind",
        "os_family",
        "collect_mode",
        "status",
        "last_sample_at",
        "created_at",
        "updated_at",
    }
    if sort_by not in allowed_sort:
        sort_by = "updated_at"
    direction = DESCENDING if sort_dir.lower() == "desc" else ASCENDING

    query: dict[str, Any] = {}
    if domain:
        d = domain.strip().lower()
        if d not in DOMAINS:
            raise MonitorTargetsError(
                f"Invalid domain '{domain}' (expected one of: {', '.join(DOMAINS)})",
                status_code=422,
            )
        query["domain"] = d
    if target_kind:
        query["target_kind"] = target_kind.strip()
    if os_family:
        fam = os_family.strip().lower()
        if fam not in OS_FAMILIES:
            raise MonitorTargetsError(
                f"Invalid os_family '{os_family}' "
                f"(expected one of: {', '.join(OS_FAMILIES)})",
                status_code=422,
            )
        query["os_family"] = fam
    if collect_mode:
        mode = collect_mode.strip().upper()
        if mode not in {"AGENTLESS", "AGENT"}:
            raise MonitorTargetsError(
                "Invalid collect_mode (expected AGENTLESS or AGENT)",
                status_code=422,
            )
        query["collect_mode"] = mode
    if status:
        st = status.strip().lower()
        if st not in TARGET_STATUSES:
            raise MonitorTargetsError(
                f"Invalid status '{status}' "
                f"(expected one of: {', '.join(TARGET_STATUSES)})",
                status_code=422,
            )
        query["status"] = st
    if component_id:
        query["component_id"] = component_id.strip()
    if q:
        term = q.strip()
        if term:
            query["$or"] = [
                {"name_snapshot": {"$regex": term, "$options": "i"}},
                {"component_id": {"$regex": term, "$options": "i"}},
                {"target_id": {"$regex": term, "$options": "i"}},
                {"target_kind": {"$regex": term, "$options": "i"}},
            ]

    filt = merge_tenant_filter(query, tid)
    coll = _targets()
    total = coll.count_documents(filt)
    cursor = (
        coll.find(filt)
        .sort([(sort_by, direction)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [_serialize(doc) for doc in cursor]
    # Attach latest sample summary (one query per page — fine for SIMULATED v1).
    for item in items:
        if item is None:
            continue
        latest = list_metrics(
            tenant_id=tid,
            target_id=item["target_id"],
            page=1,
            page_size=3,
            latest_only=True,
        )
        item["latest_metrics"] = latest.get("items") or []

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "items": items,
        "tenant_id": tid,
        "execution_mode": EXECUTION_MODE,
        "live_probes": False,
        "filters": {
            "domain": domain,
            "target_kind": target_kind,
            "os_family": os_family,
            "collect_mode": collect_mode,
            "status": status,
            "component_id": component_id,
            "q": q,
        },
    }


def get_target(*, tenant_id: str, target_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _targets().find_one(
        merge_tenant_filter({"target_id": target_id.strip()}, tid)
    )
    return _serialize(doc)


def list_metrics(
    *,
    tenant_id: str,
    target_id: str,
    metric_name: str | None = None,
    page: int = 1,
    page_size: int = 50,
    latest_only: bool = False,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    target = get_target(tenant_id=tid, target_id=target_id)
    if target is None:
        raise MonitorTargetsError(
            f"Target '{target_id}' not found", status_code=404
        )
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    query: dict[str, Any] = {"target_id": target_id.strip()}
    if metric_name:
        query["metric_name"] = metric_name.strip()
    filt = merge_tenant_filter(query, tid)
    coll = _samples()

    if latest_only:
        # Newest sample per metric_name.
        pipeline = [
            {"$match": filt},
            {"$sort": {"observed_at": DESCENDING}},
            {
                "$group": {
                    "_id": "$metric_name",
                    "doc": {"$first": "$$ROOT"},
                }
            },
            {"$replaceRoot": {"newRoot": "$doc"}},
            {"$sort": {"metric_name": ASCENDING}},
            {"$limit": page_size},
        ]
        items = [_serialize(doc) for doc in coll.aggregate(pipeline)]
        return {
            "total": len(items),
            "page": 1,
            "page_size": page_size,
            "total_pages": 1,
            "items": items,
            "target_id": target_id,
            "component_id": target.get("component_id"),
            "tenant_id": tid,
            "execution_mode": EXECUTION_MODE,
            "live_probes": False,
        }

    total = coll.count_documents(filt)
    cursor = (
        coll.find(filt)
        .sort([("observed_at", DESCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [_serialize(doc) for doc in cursor]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if page_size else 0,
        "items": items,
        "target_id": target_id,
        "component_id": target.get("component_id"),
        "tenant_id": tid,
        "execution_mode": EXECUTION_MODE,
        "live_probes": False,
    }
