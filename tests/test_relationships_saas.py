"""Master Phase 9 — Relationships SaaS wrap regressions.

Covers tenant denial, CMDB + custom-table endpoints, ports/types catalog,
and entitlements stub (no payment system).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.tenancy import MIGRATION_TENANT_ID

OTHER_TENANT_ID = "tenant-rel-saas-other"
OTHER_REL_ID = "rel-saas-other-001"
OTHER_COMPONENT_ID = "rel-saas-other-srv"


def _now():
    return datetime.now(timezone.utc)


def _seed_cmdb(client: TestClient, headers: dict[str, str]) -> None:
    for payload in (
        {
            "component_id": "rel9-srv",
            "component_type": "Server",
            "name": "rel9-host",
            "environment": "prod",
            "hostname": "rel9-host",
            "os_family": "RHEL",
            "os_version": "9",
        },
        {
            "component_id": "rel9-mw",
            "component_type": "Middleware",
            "name": "rel9-mw",
            "environment": "prod",
            "product_type": "WebLogic",
            "product_version": "14",
        },
        {
            "component_id": "rel9-db",
            "component_type": "Database",
            "name": "rel9-db",
            "environment": "prod",
            "product_type": "Oracle",
            "product_version": "19c",
        },
    ):
        assert client.post("/api/components", headers=headers, json=payload).status_code == 201


@pytest.fixture()
def other_tenant_relationship(clean_db):
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
                "display_name": "Rel SaaS Other",
                "slug": "rel-saas-other",
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
            "name": "other-srv",
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
    db["cmdb_relationships"].insert_one(
        {
            "relationship_id": OTHER_REL_ID,
            "source_component_id": OTHER_COMPONENT_ID,
            "target_component_id": OTHER_COMPONENT_ID + "-tgt",
            "relationship_type": "DEPENDS_ON",
            "protocol": "TCP",
            "source_port": 443,
            "target_port": 443,
            "discovery_method": "manually_configured",
            "verification_status": "unverified",
            "confidence": "medium",
            "duplicate_key": f"iso-dup-{OTHER_REL_ID}",
            "tenant_id": OTHER_TENANT_ID,
            "created_at": now,
            "updated_at": now,
        }
    )
    yield {
        "tenant_id": OTHER_TENANT_ID,
        "relationship_id": OTHER_REL_ID,
        "component_id": OTHER_COMPONENT_ID,
    }


def test_relationship_crud_tenant_scoped_and_cross_tenant_denied(
    client: TestClient, auth_headers: dict[str, str], other_tenant_relationship
) -> None:
    _seed_cmdb(client, auth_headers)
    created = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "relationship_id": "rel9-cmdb-1",
            "source_component_id": "rel9-mw",
            "target_component_id": "rel9-srv",
            "relationship_type": "HOSTED_ON",
            "protocol": "TCP",
            "source_port": None,
            "target_port": 7001,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["tenant_id"] == MIGRATION_TENANT_ID
    assert body["source_port"] is None
    assert body["target_port"] == 7001
    assert body.get("source_table") in (None, "Middleware")
    assert "ports" not in body

    listed = client.get("/api/relationships", headers=auth_headers)
    assert listed.status_code == 200
    ids = {r["relationship_id"] for r in listed.json()["items"]}
    assert "rel9-cmdb-1" in ids
    assert OTHER_REL_ID not in ids

    other_id = other_tenant_relationship["relationship_id"]
    assert client.get(f"/api/relationships/{other_id}", headers=auth_headers).status_code == 404
    assert (
        client.put(
            f"/api/relationships/{other_id}",
            headers=auth_headers,
            json={"verification_status": "verified"},
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/relationships/{other_id}", headers=auth_headers).status_code
        == 404
    )

    # Cannot create an edge that points at another tenant's component id.
    denied = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "rel9-mw",
            "target_component_id": other_tenant_relationship["component_id"],
            "relationship_type": "DEPENDS_ON",
        },
    )
    assert denied.status_code == 422

    updated = client.put(
        "/api/relationships/rel9-cmdb-1",
        headers=auth_headers,
        json={"source_port": 45000, "verification_status": "verified"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["source_port"] == 45000
    assert updated.json()["target_port"] == 7001

    deleted = client.delete("/api/relationships/rel9-cmdb-1", headers=auth_headers)
    assert deleted.status_code == 200
    assert client.get("/api/relationships/rel9-cmdb-1", headers=auth_headers).status_code == 404


def test_cmdb_only_null_tables_still_work(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_cmdb(client, auth_headers)
    rel = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "rel9-mw",
            "target_component_id": "rel9-db",
            "relationship_type": "CONNECTS_TO",
            "protocol": "JDBC",
            "source_port": 4000,
            "target_port": 1521,
        },
    )
    assert rel.status_code == 201, rel.text
    body = rel.json()
    assert body["source_table"] is None
    assert body["target_table"] is None
    row = client.get("/api/relationships", headers=auth_headers).json()["rows"][0]
    assert row["protocol"] == "JDBC"
    assert row["source_port"] == "4000"
    assert row["target_port"] == "1521"
    assert row["source_table"] == "—"
    assert row["target_table"] == "—"


def test_custom_table_relationship_and_entity_refs(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_cmdb(client, auth_headers)
    assert (
        client.post(
            "/api/custom-tables",
            headers=auth_headers,
            json={"table_key": "clusters", "label": "Clusters"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/custom-tables/clusters/records",
            headers=auth_headers,
            json={"record_id": "clu-rel9", "display_name": "Cluster Rel9", "fields": {}},
        ).status_code
        == 201
    )

    typed = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "clu-rel9",
            "source_table": "clusters",
            "target_component_id": "rel9-srv",
            "target_table": "Server",
            "relationship_type": "HOSTED_ON",
            "protocol": "TCP",
            "source_port": None,
            "target_port": 22,
        },
    )
    assert typed.status_code == 201, typed.text
    assert typed.json()["source_table"] == "clusters"
    assert typed.json()["target_table"] == "Server"

    refs_all = client.get("/api/entity-refs?limit=50", headers=auth_headers)
    assert refs_all.status_code == 200
    ids = {i["entity_id"] for i in refs_all.json()["items"]}
    assert "clu-rel9" in ids
    assert "rel9-srv" in ids

    refs_custom = client.get(
        "/api/entity-refs?table=clusters&limit=50", headers=auth_headers
    )
    assert refs_custom.status_code == 200
    custom_ids = {i["entity_id"] for i in refs_custom.json()["items"]}
    assert "clu-rel9" in custom_ids
    assert "rel9-srv" not in custom_ids

    refs_server = client.get(
        "/api/entity-refs?table=Server&limit=50", headers=auth_headers
    )
    assert refs_server.status_code == 200
    server_ids = {i["entity_id"] for i in refs_server.json()["items"]}
    assert "rel9-srv" in server_ids
    assert "clu-rel9" not in server_ids


def test_types_catalog_and_validation_rules(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_cmdb(client, auth_headers)
    types = client.get("/api/relationships/types", headers=auth_headers)
    assert types.status_code == 200
    keys = {t["relationship_type"] for t in types.json()["types"]}
    assert keys == {"HOSTED_ON", "DEPENDS_ON", "CONNECTS_TO", "ROUTES_TO"}

    self_ref = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "rel9-srv",
            "target_component_id": "rel9-srv",
            "relationship_type": "DEPENDS_ON",
        },
    )
    assert self_ref.status_code == 422

    bad_port = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "rel9-mw",
            "target_component_id": "rel9-db",
            "relationship_type": "CONNECTS_TO",
            "source_port": 0,
            "target_port": 1521,
        },
    )
    assert bad_port.status_code == 422

    first = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "rel9-mw",
            "target_component_id": "rel9-db",
            "relationship_type": "CONNECTS_TO",
            "protocol": "TCP",
            "source_port": 1,
            "target_port": 1521,
        },
    )
    assert first.status_code == 201, first.text
    dup = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "rel9-mw",
            "target_component_id": "rel9-db",
            "relationship_type": "CONNECTS_TO",
            "protocol": "TCP",
            "source_port": 1,
            "target_port": 1521,
        },
    )
    assert dup.status_code == 409


def test_entitlements_stub_unlimited_and_limit_enforced(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    ents = client.get("/api/entitlements", headers=auth_headers)
    assert ents.status_code == 200, ents.text
    body = ents.json()
    assert body["tenant_id"] == MIGRATION_TENANT_ID
    assert body["billing_enabled"] is False
    assert body["payment_provider"] is None
    assert body["limits"]["relationships"] is None

    _seed_cmdb(client, auth_headers)
    ok = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "rel9-mw",
            "target_component_id": "rel9-srv",
            "relationship_type": "HOSTED_ON",
        },
    )
    assert ok.status_code == 201, ok.text

    with patch(
        "app.services.entitlements.relationship_limit", return_value=1
    ):
        blocked = client.post(
            "/api/relationships",
            headers=auth_headers,
            json={
                "source_component_id": "rel9-mw",
                "target_component_id": "rel9-db",
                "relationship_type": "CONNECTS_TO",
            },
        )
        assert blocked.status_code == 403
        assert "limit" in blocked.text.lower()


def test_relationships_grid_includes_table_columns_and_ui_markers(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    cfg = client.get("/api/column-configurations/relationships", headers=auth_headers)
    assert cfg.status_code == 200
    keys = [c["column_key"] for c in cfg.json()["columns"]]
    assert "source_table" in keys
    assert "target_table" in keys
    assert "protocol" in keys
    assert "source_port" in keys
    assert "target_port" in keys
    locked = {c["column_key"] for c in cfg.json()["columns"] if c.get("locked")}
    assert {"protocol", "source_port", "target_port", "actions"} <= locked
    assert "source_table" not in locked

    html = client.get("/", headers=auth_headers).text
    assert 'id="relSourceTable"' in html
    assert 'id="relTargetTable"' in html
    assert 'id="entityIdListSource"' in html
    assert 'id="entityIdListTarget"' in html
    assert 'id="relProtocol"' in html
    assert 'id="relSourcePort"' in html
    assert 'id="relTargetPort"' in html
    from app import __version__

    assert __version__ in html
    assert 'id="entitlementsPanel"' in html
    js = client.get("/static/js/cmdb.js", headers=auth_headers).text
    assert "syncRelEntityDatalists" in js
    assert "loadEntitlements" in js
