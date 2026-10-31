#!/usr/bin/env python3
"""Idempotent SVRMON24 demo/sample data seeder.

Creates a multi-tier CMDB topology with stable ``demo-*`` / ``demo_`` IDs.
Re-runs skip existing records. Use ``--wipe-demo`` to remove only demo data.

Usage (PowerShell)::

    cd C:\\Users\\Pradeep\\Projects\\svrmon24
    .\\.venv\\Scripts\\Activate.ps1
    python scripts\\seed_sample_data.py
    python scripts\\seed_sample_data.py --wipe-demo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path when invoked as a script
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db import ping_database, reset_client_for_tests
from app.models.components import ComponentCreate
from app.models.custom_fields import CustomFieldCreate
from app.models.diagnostics import DiagnosticStartRequest
from app.models.relationships import RelationshipCreate
from app.services import ai_analysis as ai_analysis_service
from app.services import components as components_service
from app.services import custom_fields as custom_fields_service
from app.services import diagnostics as diagnostics_service
from app.services import relationships as relationships_service
from app.services.components import ComponentError
from app.services.custom_fields import CustomFieldError
from app.services.relationships import RelationshipError


DEMO_PREFIX = "demo-"
DEMO_FIELD_PREFIX = "demo_"
DEMO_NOTE_TAG = "[demo-seed]"


def _ok(msg: str) -> None:
    print(f"  [ok] {msg}")


def _skip(msg: str) -> None:
    print(f"  [skip] {msg}")


def _fail(msg: str) -> None:
    print(f"  [fail] {msg}", file=sys.stderr)


def wipe_demo() -> dict[str, int]:
    """Delete only demo-* / demo_ sample records. Leaves other user data alone."""
    from app.db import get_database

    db = get_database()
    counts = {
        "diagnostics": db["diagnostic_history"].delete_many(
            {
                "$or": [
                    {"component_id": {"$regex": f"^{DEMO_PREFIX}"}},
                    {"notes": {"$regex": DEMO_NOTE_TAG}},
                    {"diagnostic_id": {"$regex": f"^{DEMO_PREFIX}"}},
                ]
            }
        ).deleted_count,
        "relationships": db["cmdb_relationships"].delete_many(
            {"relationship_id": {"$regex": f"^{DEMO_PREFIX}"}}
        ).deleted_count,
        "components": db["components"].delete_many(
            {"component_id": {"$regex": f"^{DEMO_PREFIX}"}}
        ).deleted_count,
        "custom_fields": db["custom_field_definitions"].delete_many(
            {"field_key": {"$regex": f"^{DEMO_FIELD_PREFIX}"}}
        ).deleted_count,
    }
    return counts


def ensure_custom_field() -> str:
    key = "demo_cost_center"
    existing = custom_fields_service.get_definition(key)
    if existing:
        _skip(f"custom field {key}")
        return "skipped"
    try:
        custom_fields_service.create_definition(
            CustomFieldCreate(
                field_key=key,
                label="Demo Cost Center",
                field_type="string",
                applies_to=["*"],
                required=False,
                enum_values=[],
            )
        )
        _ok(f"custom field {key}")
        return "created"
    except CustomFieldError as exc:
        _skip(f"custom field {key}: {exc.message}")
        return "skipped"


def ensure_component(payload: dict[str, Any]) -> str:
    cid = payload["component_id"]
    if components_service.get_component(cid):
        _skip(f"component {cid}")
        return "skipped"
    try:
        components_service.create_component(ComponentCreate(**payload))
        _ok(f"component {cid} ({payload['component_type']})")
        return "created"
    except ComponentError as exc:
        if exc.status_code == 409:
            _skip(f"component {cid} (exists)")
            return "skipped"
        raise


def ensure_relationship(payload: dict[str, Any]) -> str:
    rid = payload["relationship_id"]
    if relationships_service.get_relationship(rid):
        _skip(f"relationship {rid}")
        return "skipped"
    try:
        relationships_service.create_relationship(RelationshipCreate(**payload))
        ports = f"src={payload.get('source_port')} tgt={payload.get('target_port')}"
        _ok(
            f"relationship {rid} {payload['relationship_type']} "
            f"{payload['source_component_id']}->{payload['target_component_id']} "
            f"proto={payload.get('protocol')} {ports}"
        )
        return "created"
    except RelationshipError as exc:
        if exc.status_code == 409:
            _skip(f"relationship {rid} (exists)")
            return "skipped"
        raise


def ensure_simulated_diagnostic(component_id: str) -> str:
    """Create one SIMULATED diagnostic + rule-based AI analysis if missing."""
    history = diagnostics_service.list_diagnostics(
        component_id=component_id, page=1, page_size=50
    )
    for item in history.get("items") or []:
        # list items may be summary rows; fetch detail for notes
        detail = diagnostics_service.get_diagnostic(item["diagnostic_id"])
        if detail and DEMO_NOTE_TAG in str(detail.get("notes") or ""):
            _skip(f"diagnostic for {component_id} ({detail['diagnostic_id']})")
            return "skipped"

    doc = diagnostics_service.start_diagnostic(
        DiagnosticStartRequest(
            component_id=component_id,
            profile_name="basic-health",
            notes=f"{DEMO_NOTE_TAG} Sample SIMULATED diagnostic for UI demo.",
        )
    )
    assert doc.get("execution_mode") == "SIMULATED"
    diag_id = doc["diagnostic_id"]
    _ok(f"diagnostic {diag_id} for {component_id} (SIMULATED)")

    # Attach rule-based fallback analysis (no Ollama required)
    updated = ai_analysis_service.analyze_diagnostic(diag_id, force_fallback=True)
    source = (updated.get("ai_analysis") or {}).get("source")
    _ok(f"ai analysis on {diag_id} source={source}")
    return "created"


def seed() -> dict[str, int]:
    stats = {"created": 0, "skipped": 0}

    def tally(result: str) -> None:
        stats[result if result in stats else "created"] = stats.get(result, 0) + 1

    print("Seeding custom fields…")
    tally(ensure_custom_field())

    print("Seeding components…")
    components: list[dict[str, Any]] = [
        {
            "component_id": "demo-net-edge",
            "component_type": "Network",
            "name": "Edge Load Balancer",
            "environment": "prod",
            "status": "active",
            "device_name": "lb-edge-01",
            "device_type": "load_balancer",
            "management_ip": "10.10.0.5",
            "virtual_ip": "10.10.0.10",
            "listener_port": 443,
            "custom_fields": {"demo_cost_center": "NET-OPS"},
        },
        {
            "component_id": "demo-srv-web01",
            "component_type": "Server",
            "name": "Web Tier 01",
            "environment": "prod",
            "status": "active",
            "hostname": "web01.demo.local",
            "ip_address": "10.10.1.11",
            "os_family": "RHEL",
            "os_version": "9.4",
            "custom_fields": {"demo_cost_center": "WEB"},
        },
        {
            "component_id": "demo-srv-app01",
            "component_type": "Server",
            "name": "App Tier 01",
            "environment": "prod",
            "status": "active",
            "hostname": "app01.demo.local",
            "ip_address": "10.10.2.21",
            "os_family": "RHEL",
            "os_version": "9.4",
            "custom_fields": {"demo_cost_center": "APP"},
        },
        {
            "component_id": "demo-srv-db01",
            "component_type": "Server",
            "name": "DB Tier 01",
            "environment": "prod",
            "status": "active",
            "hostname": "db01.demo.local",
            "ip_address": "10.10.3.31",
            "os_family": "RHEL",
            "os_version": "8.10",
            "custom_fields": {"demo_cost_center": "DATA"},
        },
        {
            "component_id": "demo-mware-wls",
            "component_type": "Middleware",
            "name": "WebLogic Orders",
            "environment": "prod",
            "status": "active",
            "product_type": "WebLogic",
            "product_version": "14.1.1",
            "instance_name": "orders_domain",
            "host_server_id": "demo-srv-app01",
            "listen_port": 7001,
            "custom_fields": {"demo_cost_center": "APP"},
        },
        {
            "component_id": "demo-db-orders",
            "component_type": "Database",
            "name": "Orders DB",
            "environment": "prod",
            "status": "active",
            "product_type": "Oracle",
            "product_version": "19c",
            "instance_name": "ORCL",
            "endpoint": "db01.demo.local:1521/ORCL",
            "listen_port": 1521,
            "custom_fields": {"demo_cost_center": "DATA"},
        },
        {
            "component_id": "demo-app-billing",
            "component_type": "Application",
            "name": "Billing Service",
            "environment": "prod",
            "status": "active",
            "application_name": "Billing",
            "application_type": "backend",
            "service_url": "https://billing.demo.local",
            "business_criticality": "high",
            "owner": "finance-platform",
            "custom_fields": {"demo_cost_center": "FIN"},
        },
        {
            "component_id": "demo-app-portal",
            "component_type": "Application",
            "name": "Customer Portal",
            "environment": "prod",
            "status": "active",
            "application_name": "Portal",
            "application_type": "web",
            "service_url": "https://portal.demo.local",
            "business_criticality": "high",
            "owner": "digital",
            "custom_fields": {"demo_cost_center": "DIGITAL"},
        },
        {
            "component_id": "demo-srv-batch",
            "component_type": "Server",
            "name": "Batch Worker (review)",
            "environment": "nonprod",
            "status": "inactive",
            "hostname": "batch01.demo.local",
            "ip_address": "10.20.1.40",
            "os_family": "Windows Server",
            "os_version": "2022",
            "custom_fields": {"demo_cost_center": "BATCH"},
        },
    ]
    for payload in components:
        tally(ensure_component(payload))

    print("Seeding relationships…")
    relationships: list[dict[str, Any]] = [
        {
            "relationship_id": "demo-rel-wls-hosted",
            "relationship_type": "HOSTED_ON",
            "source_component_id": "demo-mware-wls",
            "target_component_id": "demo-srv-app01",
            "protocol": None,
            "source_port": None,
            "target_port": None,
            "environment": "prod",
            "discovery_method": "manually_configured",
            "verification_status": "verified",
            "confidence": "high",
            "evidence_or_notes": f"{DEMO_NOTE_TAG} Middleware hosted on app server",
        },
        {
            "relationship_id": "demo-rel-db-hosted",
            "relationship_type": "HOSTED_ON",
            "source_component_id": "demo-db-orders",
            "target_component_id": "demo-srv-db01",
            "protocol": None,
            "source_port": None,
            "target_port": None,
            "environment": "prod",
            "verification_status": "verified",
            "confidence": "high",
            "evidence_or_notes": f"{DEMO_NOTE_TAG} DB instance on db host",
        },
        {
            "relationship_id": "demo-rel-billing-wls",
            "relationship_type": "DEPENDS_ON",
            "source_component_id": "demo-app-billing",
            "target_component_id": "demo-mware-wls",
            "protocol": "T3",
            "source_port": None,
            "target_port": 7001,
            "environment": "prod",
            "verification_status": "verified",
            "confidence": "high",
            "evidence_or_notes": f"{DEMO_NOTE_TAG} Billing → WebLogic",
        },
        {
            "relationship_id": "demo-rel-billing-db",
            "relationship_type": "DEPENDS_ON",
            "source_component_id": "demo-app-billing",
            "target_component_id": "demo-db-orders",
            "protocol": "TCP",
            "source_port": 45000,
            "target_port": 1521,
            "environment": "prod",
            "verification_status": "unverified",
            "confidence": "medium",
            "evidence_or_notes": f"{DEMO_NOTE_TAG} Billing → Orders DB (JDBC)",
        },
        {
            "relationship_id": "demo-rel-portal-billing",
            "relationship_type": "DEPENDS_ON",
            "source_component_id": "demo-app-portal",
            "target_component_id": "demo-app-billing",
            "protocol": "HTTPS",
            "source_port": None,
            "target_port": 443,
            "environment": "prod",
            "verification_status": "verified",
            "confidence": "high",
            "evidence_or_notes": f"{DEMO_NOTE_TAG} Portal → Billing API",
        },
        {
            "relationship_id": "demo-rel-portal-edge",
            "relationship_type": "CONNECTS_TO",
            "source_component_id": "demo-app-portal",
            "target_component_id": "demo-net-edge",
            "protocol": "HTTPS",
            "source_port": None,
            "target_port": 443,
            "environment": "prod",
            "verification_status": "verified",
            "confidence": "high",
            "evidence_or_notes": f"{DEMO_NOTE_TAG} Portal fronted by edge LB",
        },
        {
            "relationship_id": "demo-rel-edge-web",
            "relationship_type": "ROUTES_TO",
            "source_component_id": "demo-net-edge",
            "target_component_id": "demo-srv-web01",
            "protocol": "HTTPS",
            "source_port": 443,
            "target_port": 8443,
            "environment": "prod",
            "verification_status": "verified",
            "confidence": "high",
            "evidence_or_notes": f"{DEMO_NOTE_TAG} Edge routes to web tier",
        },
        {
            "relationship_id": "demo-rel-web-wls",
            "relationship_type": "CONNECTS_TO",
            "source_component_id": "demo-srv-web01",
            "target_component_id": "demo-mware-wls",
            "protocol": "HTTP",
            "source_port": None,
            "target_port": 7001,
            "environment": "prod",
            "verification_status": "unverified",
            "confidence": "medium",
            "evidence_or_notes": f"{DEMO_NOTE_TAG} Web proxy to middleware",
        },
    ]
    for payload in relationships:
        tally(ensure_relationship(payload))

    print("Seeding SIMULATED diagnostics…")
    for cid in ("demo-srv-web01", "demo-srv-app01", "demo-db-orders"):
        tally(ensure_simulated_diagnostic(cid))

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed or wipe SVRMON24 demo sample data")
    parser.add_argument(
        "--wipe-demo",
        action="store_true",
        help="Delete only demo-* / demo_ sample records, then exit",
    )
    parser.add_argument(
        "--wipe-then-seed",
        action="store_true",
        help="Wipe demo records first, then seed fresh",
    )
    args = parser.parse_args()

    get_settings.cache_clear()
    reset_client_for_tests()
    ping = ping_database()
    if not ping.get("ok"):
        _fail(f"MongoDB unavailable: {ping.get('detail')}")
        return 1
    print(f"MongoDB ok database={ping.get('database')}")

    if args.wipe_demo or args.wipe_then_seed:
        print("Wiping demo-* sample data only…")
        wiped = wipe_demo()
        print(f"  wiped: {wiped}")
        if args.wipe_demo and not args.wipe_then_seed:
            return 0

    print("Seeding demo sample data (idempotent)…")
    stats = seed()
    print(f"\nDone. created={stats['created']} skipped={stats['skipped']}")

    # Quick counts for smoke reporting
    comps = components_service.list_components(q="demo-", page=1, page_size=50)
    rels = relationships_service.list_relationships(q="demo-", page=1, page_size=50)
    diags = diagnostics_service.list_diagnostics(page=1, page_size=50)
    demo_diags = [
        i
        for i in (diags.get("items") or [])
        if str(i.get("component_id") or "").startswith(DEMO_PREFIX)
    ]
    print(
        f"Smoke counts: demo_components≈{comps.get('total')} "
        f"demo_relationships≈{rels.get('total')} "
        f"demo_diagnostics_listed={len(demo_diags)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
