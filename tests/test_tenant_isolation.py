"""Master Phase 5 — hard tenant isolation and cross-tenant denial."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.tenancy import MIGRATION_TENANT_ID

OTHER_TENANT_ID = "tenant-isolation-other"
OTHER_COMPONENT_ID = "iso-other-srv-001"
OTHER_FIELD_KEY = "iso_other_field"
OTHER_REL_ID = "iso-other-rel-001"
OTHER_DIAG_ID = "iso-other-diag-001"


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture()
def other_tenant_docs(clean_db):
    """Insert a second tenant with CMDB docs that Basic (migration) must not see."""
    from app.db import get_database
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    db = get_database()
    now = _now()
    db["tenants"].update_one(
        {"tenant_id": OTHER_TENANT_ID},
        {
            "$set": {
                "tenant_id": OTHER_TENANT_ID,
                "display_name": "Isolation Other Org",
                "slug": "isolation-other",
                "status": "active",
                "is_migration_tenant": False,
                "switchable": False,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    db["cmdb_servers"].insert_one(
        {
            "component_id": OTHER_COMPONENT_ID,
            "component_type": "Server",
            "name": "other-tenant-server",
            "environment": "prod",
            "status": "active",
            "hostname": "other.example",
            "os_family": "Linux",
            "os_version": "9",
            "tenant_id": OTHER_TENANT_ID,
            "custom_fields": {},
            "created_at": now,
            "updated_at": now,
        }
    )
    db["cmdb_field_definitions"].insert_one(
        {
            "field_key": OTHER_FIELD_KEY,
            "label": "Other Field",
            "field_type": "string",
            "applies_to": ["*"],
            "required": False,
            "enum_values": [],
            "origin": "custom",
            "storage": "custom_fields",
            "locked": False,
            "active": True,
            "tenant_id": OTHER_TENANT_ID,
            "created_at": now,
            "updated_at": now,
        }
    )
    db["cmdb_relationships"].insert_one(
        {
            "relationship_id": OTHER_REL_ID,
            "source_component_id": OTHER_COMPONENT_ID,
            "target_component_id": OTHER_COMPONENT_ID + "-tgt",
            "relationship_type": "depends_on",
            "protocol": "https",
            "source_port": 443,
            "target_port": 443,
            "discovery_method": "manual",
            "verification_status": "unverified",
            "confidence": "medium",
            "duplicate_key": f"iso-dup-{OTHER_REL_ID}",
            "tenant_id": OTHER_TENANT_ID,
            "created_at": now,
            "updated_at": now,
        }
    )
    db["diagnostic_history"].insert_one(
        {
            "diagnostic_id": OTHER_DIAG_ID,
            "timestamp": now,
            "created_at": now,
            "execution_mode": "SIMULATED",
            "profile_name": "basic-health",
            "component_id": OTHER_COMPONENT_ID,
            "component": {"component_id": OTHER_COMPONENT_ID},
            "checks": [],
            "summary": {"overall_status": "ok", "check_count": 0, "ok_count": 0},
            "labels": {"simulated": True},
            "tenant_id": OTHER_TENANT_ID,
        }
    )
    yield {
        "tenant_id": OTHER_TENANT_ID,
        "component_id": OTHER_COMPONENT_ID,
        "field_key": OTHER_FIELD_KEY,
        "relationship_id": OTHER_REL_ID,
        "diagnostic_id": OTHER_DIAG_ID,
    }


def test_backfill_null_tenant_ids(clean_db) -> None:
    from app.db import get_database
    from app.services import tenants as tenants_service
    from app.services.bootstrap import ensure_tenancy_ready

    tenants_service.ensure_migration_tenant()
    db = get_database()
    db["components"].insert_one(
        {
            "component_id": "legacy-null-tenant",
            "component_type": "Server",
            "name": "legacy",
            "environment": "lab",
            "status": "active",
            # intentionally missing tenant_id
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    result = ensure_tenancy_ready()
    assert result["ok"] is True
    assert result["isolation_enforced"] is True
    assert result["backfill"]["modified"]["components"] >= 1
    doc = db["components"].find_one({"component_id": "legacy-null-tenant"})
    assert doc is not None
    assert doc["tenant_id"] == MIGRATION_TENANT_ID
    # Phase 6: bootstrap also migrates into typed collections
    typed = db["cmdb_servers"].find_one({"component_id": "legacy-null-tenant"})
    assert typed is not None
    assert typed["tenant_id"] == MIGRATION_TENANT_ID
    assert result.get("typed_cmdb_migrate", {}).get("migrated", 0) >= 1


def test_basic_cannot_read_other_tenant_component(
    client: TestClient, auth_headers, other_tenant_docs
) -> None:
    cid = other_tenant_docs["component_id"]
    # Direct get
    resp = client.get(f"/api/components/{cid}", headers=auth_headers)
    assert resp.status_code == 404
    # List must not include other tenant
    listed = client.get("/api/components", headers=auth_headers)
    assert listed.status_code == 200
    ids = [i["component_id"] for i in listed.json().get("items") or []]
    assert cid not in ids
    assert listed.json().get("tenant_id") == MIGRATION_TENANT_ID


def test_basic_cannot_update_or_delete_other_tenant(
    client: TestClient, auth_headers, other_tenant_docs
) -> None:
    cid = other_tenant_docs["component_id"]
    upd = client.put(
        f"/api/components/{cid}",
        headers=auth_headers,
        json={"name": "hijacked"},
    )
    assert upd.status_code == 404
    deleted = client.delete(
        f"/api/components/{cid}?confirmed=true", headers=auth_headers
    )
    assert deleted.status_code == 404
    # Still present under other tenant in typed CMDB collection
    from app.db import get_database

    doc = get_database()["cmdb_servers"].find_one({"component_id": cid})
    assert doc is not None
    assert doc["tenant_id"] == OTHER_TENANT_ID
    assert doc["name"] == "other-tenant-server"


def test_basic_cannot_read_other_tenant_relationships_fields_diags_dashboard(
    client: TestClient, auth_headers, other_tenant_docs
) -> None:
    rid = other_tenant_docs["relationship_id"]
    fkey = other_tenant_docs["field_key"]
    did = other_tenant_docs["diagnostic_id"]
    cid = other_tenant_docs["component_id"]

    assert (
        client.get(f"/api/relationships/{rid}", headers=auth_headers).status_code
        == 404
    )
    assert (
        client.get(f"/api/custom-fields/{fkey}", headers=auth_headers).status_code
        == 404
    )
    assert (
        client.get(f"/api/field-definitions/{fkey}", headers=auth_headers).status_code
        == 404
    )
    assert (
        client.get(f"/api/diagnostics/{did}", headers=auth_headers).status_code == 404
    )
    assert (
        client.get(f"/api/dependencies/{cid}", headers=auth_headers).status_code
        == 404
    )

    dash = client.get("/api/dashboard/summary", headers=auth_headers)
    assert dash.status_code == 200
    body = dash.json()
    assert body.get("tenant_id") == MIGRATION_TENANT_ID
    assert body.get("total_components") == 0
    assert body.get("total_relationships") == 0
    diag_ids = [
        d.get("diagnostic_id") for d in body.get("recent_diagnostics") or []
    ]
    assert did not in diag_ids


def test_writes_stamp_current_tenant(
    client: TestClient, auth_headers, clean_db
) -> None:
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    created = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Server",
            "name": "iso-write-srv",
            "environment": "lab",
            "status": "active",
            "hostname": "iso-write.example",
            "os_family": "Linux",
            "os_version": "9",
        },
    )
    assert created.status_code in (200, 201), created.text
    body = created.json()
    assert body["tenant_id"] == MIGRATION_TENANT_ID

    listed = client.get("/api/components", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["component_id"] == body["component_id"]


def test_component_id_remains_globally_unique(
    client: TestClient, auth_headers, other_tenant_docs
) -> None:
    """Global unique component_id: cannot create same id under migration tenant."""
    resp = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_id": other_tenant_docs["component_id"],
            "component_type": "Server",
            "name": "collision",
            "environment": "lab",
            "status": "active",
            "hostname": "collision.example",
            "os_family": "Linux",
            "os_version": "9",
        },
    )
    assert resp.status_code == 409


def test_me_and_tenants_report_isolation_on(
    client: TestClient, auth_headers, clean_db
) -> None:
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    me = client.get("/api/me", headers=auth_headers)
    assert me.status_code == 200
    assert me.json()["isolation_enforced"] is True
    assert me.json()["org_switcher_enabled"] is True
    assert me.json()["current_tenant_id"] == MIGRATION_TENANT_ID

    current = client.get("/api/tenants/current", headers=auth_headers)
    assert current.status_code == 200
    assert current.json()["isolation_enforced"] is True

    # Cross-tenant tenant metadata denied
    other = client.get(f"/api/tenants/{OTHER_TENANT_ID}", headers=auth_headers)
    assert other.status_code == 404


def test_service_layer_scopes_queries(clean_db, other_tenant_docs) -> None:
    from app.services import components as components_service
    from app.services import dashboard as dashboard_service

    assert (
        components_service.get_component(
            OTHER_COMPONENT_ID, tenant_id=MIGRATION_TENANT_ID
        )
        is None
    )
    other = components_service.get_component(
        OTHER_COMPONENT_ID, tenant_id=OTHER_TENANT_ID
    )
    assert other is not None
    assert other["tenant_id"] == OTHER_TENANT_ID

    legacy_dash = dashboard_service.get_dashboard_summary(
        tenant_id=MIGRATION_TENANT_ID
    )
    assert legacy_dash["total_components"] == 0
    other_dash = dashboard_service.get_dashboard_summary(tenant_id=OTHER_TENANT_ID)
    assert other_dash["total_components"] == 1
