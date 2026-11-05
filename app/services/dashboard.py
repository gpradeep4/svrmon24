"""Dashboard aggregates from live MongoDB collections (tenant-scoped)."""

from __future__ import annotations

from typing import Any

from ..db import get_database
from ..serialization import serialize_document
from ..tenancy import require_tenant_id, tenant_filter


def _count_by(collection_name: str, field: str, *, tenant_id: str) -> dict[str, int]:
    db = get_database()
    tid = require_tenant_id(tenant_id)
    pipeline = [
        {"$match": tenant_filter(tid)},
        {"$group": {"_id": f"${field}", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    out: dict[str, int] = {}
    for row in db[collection_name].aggregate(pipeline):
        key = row.get("_id")
        label = "unknown" if key is None or key == "" else str(key)
        out[label] = int(row.get("count") or 0)
    return out


def get_dashboard_summary(
    *, tenant_id: str, recent_limit: int = 8
) -> dict[str, Any]:
    """Build dashboard widgets from live CMDB / diagnostic data for one tenant."""
    tid = require_tenant_id(tenant_id)
    recent_limit = max(1, min(int(recent_limit), 50))
    db = get_database()
    components = db["components"]
    relationships = db["cmdb_relationships"]
    diagnostics = db["diagnostic_history"]
    scope = tenant_filter(tid)

    total_components = components.count_documents(scope)
    total_relationships = relationships.count_documents(scope)
    by_type = _count_by("components", "component_type", tenant_id=tid)
    by_environment = _count_by("components", "environment", tenant_id=tid)

    recent_diagnostics = list(
        diagnostics.find(scope, {"_id": 0})
        .sort("timestamp", -1)
        .limit(recent_limit)
    )

    findings: list[dict[str, Any]] = []
    for doc in diagnostics.find(scope).sort("timestamp", -1).limit(40):
        summary = doc.get("summary") or {}
        overall = str(summary.get("overall_status") or "ok")
        checks = doc.get("checks") or []
        bad_checks = [
            c
            for c in checks
            if isinstance(c, dict) and c.get("status") not in {None, "ok"}
        ]
        if overall == "ok" and not bad_checks:
            continue
        findings.append(
            {
                "diagnostic_id": doc.get("diagnostic_id"),
                "timestamp": doc.get("timestamp"),
                "component_id": (doc.get("component") or {}).get("component_id"),
                "profile_name": doc.get("profile_name"),
                "execution_mode": doc.get("execution_mode"),
                "overall_status": overall,
                "non_ok_checks": [
                    {
                        "check_id": c.get("check_id"),
                        "status": c.get("status"),
                        "value": c.get("value"),
                        "data_source": c.get("data_source"),
                        "synthetic": c.get("synthetic"),
                    }
                    for c in bad_checks[:8]
                ],
                "derived_from_simulated_data": True,
                "labels": {
                    "banner": "SIMULATED / SYNTHETIC_DEMO findings — not live telemetry"
                },
            }
        )
        if len(findings) >= recent_limit:
            break

    review_map: dict[str, dict[str, Any]] = {}

    for doc in components.find(
        {**scope, "status": {"$in": ["inactive", "decommissioned", "unknown"]}},
        {"_id": 0, "component_id": 1, "name": 1, "hostname": 1, "component_type": 1,
         "environment": 1, "status": 1},
    ):
        cid = doc.get("component_id")
        if not cid:
            continue
        review_map[cid] = {
            "component_id": cid,
            "name": doc.get("name") or doc.get("hostname"),
            "component_type": doc.get("component_type"),
            "environment": doc.get("environment"),
            "status": doc.get("status"),
            "reasons": [f"status={doc.get('status')}"],
        }

    for rel in relationships.find(
        {**scope, "verification_status": {"$ne": "verified"}},
        {"_id": 0, "source_component_id": 1, "target_component_id": 1,
         "relationship_id": 1, "verification_status": 1},
    ):
        for side in ("source_component_id", "target_component_id"):
            cid = rel.get(side)
            if not cid:
                continue
            entry = review_map.setdefault(
                cid,
                {
                    "component_id": cid,
                    "name": None,
                    "component_type": None,
                    "environment": None,
                    "status": None,
                    "reasons": [],
                },
            )
            reason = (
                f"unverified relationship {rel.get('relationship_id')} "
                f"({rel.get('verification_status')})"
            )
            if reason not in entry["reasons"]:
                entry["reasons"].append(reason)

    for finding in findings:
        cid = finding.get("component_id")
        if not cid:
            continue
        entry = review_map.setdefault(
            cid,
            {
                "component_id": cid,
                "name": None,
                "component_type": None,
                "environment": None,
                "status": None,
                "reasons": [],
            },
        )
        reason = (
            f"simulated diagnostic {finding.get('diagnostic_id')} "
            f"overall={finding.get('overall_status')}"
        )
        if reason not in entry["reasons"]:
            entry["reasons"].append(reason)

    missing_ids = [
        cid
        for cid, row in review_map.items()
        if row.get("name") is None or row.get("status") is None
    ]
    if missing_ids:
        for doc in components.find(
            {**scope, "component_id": {"$in": missing_ids}},
            {"_id": 0, "component_id": 1, "name": 1, "hostname": 1,
             "component_type": 1, "environment": 1, "status": 1},
        ):
            cid = doc["component_id"]
            entry = review_map[cid]
            entry["name"] = entry.get("name") or doc.get("name") or doc.get("hostname")
            entry["component_type"] = entry.get("component_type") or doc.get(
                "component_type"
            )
            entry["environment"] = entry.get("environment") or doc.get("environment")
            entry["status"] = entry.get("status") or doc.get("status")

    critical = sorted(
        review_map.values(),
        key=lambda r: (-len(r.get("reasons") or []), str(r.get("component_id") or "")),
    )[: recent_limit * 2]

    return serialize_document(
        {
            "total_components": total_components,
            "components_by_type": by_type,
            "components_by_environment": by_environment,
            "total_relationships": total_relationships,
            "recent_diagnostics": recent_diagnostics,
            "recent_findings": findings,
            "critical_components_requiring_review": critical,
            "tenant_id": tid,
            "labels": {
                "diagnostics_mode": "SIMULATED",
                "findings_banner": (
                    "Diagnostic findings are SIMULATED / SYNTHETIC_DEMO — not live telemetry"
                ),
            },
        }
    )  # type: ignore[return-value]
