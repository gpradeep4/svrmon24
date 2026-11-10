"""Master Phase 10 — Dependencies / impact SaaS wrap regressions.

Covers tenant denial, CMDB + custom-table graph edges, protocol/ports on edges,
IMPACT_DISCLAIMER language, and max_dependency_depth entitlements stub.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.services.dependencies import IMPACT_DISCLAIMER
from app.tenancy import MIGRATION_TENANT_ID

OTHER_TENANT_ID = "tenant-dep-saas-other"
OTHER_COMPONENT_ID = "dep-saas-other-srv"


def _now():
    return datetime.now(timezone.utc)


def _seed_cmdb_graph(client: TestClient, headers: dict[str, str]) -> None:
    for payload in (
        {
            "component_id": "dep10-srv",
            "component_type": "Server",
            "name": "dep10-host",
            "environment": "prod",
            "status": "active",
            "hostname": "dep10-host",
            "os_family": "RHEL",
            "os_version": "9",
        },
        {
            "component_id": "dep10-mw",
            "component_type": "Middleware",
            "name": "dep10-mw",
            "environment": "prod",
            "status": "active",
            "product_type": "WebLogic",
            "product_version": "14",
        },
        {
            "component_id": "dep10-db",
            "component_type": "Database",
            "name": "dep10-db",
            "environment": "prod",
            "status": "active",
            "product_type": "Oracle",
            "product_version": "19c",
        },
        {
            "component_id": "dep10-app",
            "component_type": "Application",
            "name": "dep10-portal",
            "environment": "prod",
            "status": "active",
            "application_name": "dep10-portal",
        },
    ):
        assert (
            client.post("/api/components", headers=headers, json=payload).status_code
            == 201
        )

    assert (
        client.post(
            "/api/relationships",
            headers=headers,
            json={
                "source_component_id": "dep10-mw",
                "target_component_id": "dep10-srv",
                "relationship_type": "HOSTED_ON",
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/relationships",
            headers=headers,
            json={
                "source_component_id": "dep10-mw",
                "target_component_id": "dep10-db",
                "relationship_type": "CONNECTS_TO",
                "protocol": "JDBC",
                "source_port": 45000,
                "target_port": 1521,
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/relationships",
            headers=headers,
            json={
                "source_component_id": "dep10-app",
                "target_component_id": "dep10-mw",
                "relationship_type": "DEPENDS_ON",
            },
        ).status_code
        == 201
    )


@pytest.fixture()
def other_tenant_component(clean_db):
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
                "display_name": "Dep SaaS Other",
                "slug": "dep-saas-other",
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
    return {"component_id": OTHER_COMPONENT_ID, "tenant_id": OTHER_TENANT_ID}


def test_dependency_endpoints_tenant_scoped(
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
    other_tenant_component,
) -> None:
    _seed_cmdb_graph(client, auth_headers)
    cid = other_tenant_component["component_id"]

    assert client.get(f"/api/dependencies/{cid}", headers=auth_headers).status_code == 404
    assert (
        client.get(f"/api/dependencies/{cid}/upstream", headers=auth_headers).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/dependencies/{cid}/downstream", headers=auth_headers
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/dependencies/{cid}/impact", headers=auth_headers).status_code
        == 404
    )

    ok = client.get("/api/dependencies/dep10-app?depth=5", headers=auth_headers)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["tenant_id"] == MIGRATION_TENANT_ID
    assert body["selected"]["component_id"] == "dep10-app"
    ids = {n["component_id"] for n in body["graph"]["nodes"]}
    assert cid not in ids
    assert "dep10-srv" in ids


def test_cmdb_null_table_edges_preserve_ports(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_cmdb_graph(client, auth_headers)
    up = client.get(
        "/api/dependencies/dep10-mw/upstream?depth=2", headers=auth_headers
    )
    assert up.status_code == 200, up.text
    body = up.json()
    jdbc = next(
        e
        for e in body["edges"]
        if e.get("protocol") == "JDBC" or e.get("target_port") == 1521
    )
    assert jdbc["protocol"] == "JDBC"
    assert jdbc["source_port"] == 45000
    assert jdbc["target_port"] == 1521
    assert "ports" not in jdbc
    assert jdbc.get("source_table") in (None, "—", "Middleware") or jdbc[
        "source_table"
    ] is None
    row = next(r for r in body["rows"] if r["component_id"] == "dep10-db")
    assert row["protocol"] == "JDBC"
    assert row["source_port"] == "45000"
    assert row["target_port"] == "1521"
    assert row["source_table"] == "—"
    assert row["target_table"] == "—"


def test_custom_table_relationship_edges_in_graph(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_cmdb_graph(client, auth_headers)
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
            json={
                "record_id": "clu-dep10",
                "display_name": "Cluster Dep10",
                "fields": {},
            },
        ).status_code
        == 201
    )
    rel = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "clu-dep10",
            "source_table": "clusters",
            "target_component_id": "dep10-srv",
            "target_table": "Server",
            "relationship_type": "HOSTED_ON",
            "protocol": "TCP",
            "source_port": None,
            "target_port": 22,
        },
    )
    assert rel.status_code == 201, rel.text

    # Start from custom record (table hint + blind lookup).
    hinted = client.get(
        "/api/dependencies/clu-dep10?depth=2&table=clusters",
        headers=auth_headers,
    )
    assert hinted.status_code == 200, hinted.text
    hinted_body = hinted.json()
    assert hinted_body["selected"]["kind"] == "custom"
    assert hinted_body["selected"]["ref_table"] == "clusters"
    up_ids = {n["component_id"] for n in hinted_body["upstream"]["nodes"]}
    assert "dep10-srv" in up_ids
    edge = next(
        e for e in hinted_body["upstream"]["edges"] if e["target_component_id"] == "dep10-srv"
    )
    assert edge["source_table"] == "clusters"
    assert edge["target_table"] == "Server"
    assert edge["protocol"] == "TCP"
    assert edge["target_port"] == 22
    assert edge["source_port"] is None
    row = next(
        r for r in hinted_body["upstream"]["rows"] if r["component_id"] == "dep10-srv"
    )
    assert row["source_table"] == "clusters"
    assert row["target_table"] == "Server"
    assert row["protocol"] == "TCP"
    assert row["target_port"] == "22"

    # Blind start (no table) still resolves unique custom record_id.
    blind = client.get(
        "/api/dependencies/clu-dep10/upstream?depth=1", headers=auth_headers
    )
    assert blind.status_code == 200, blind.text
    assert "dep10-srv" in {n["component_id"] for n in blind.json()["nodes"]}

    # Downstream from server includes the custom cluster.
    down = client.get(
        "/api/dependencies/dep10-srv/downstream?depth=2", headers=auth_headers
    )
    assert down.status_code == 200
    down_ids = {n["component_id"] for n in down.json()["nodes"]}
    assert "clu-dep10" in down_ids
    custom_node = next(n for n in down.json()["nodes"] if n["component_id"] == "clu-dep10")
    assert custom_node["kind"] == "custom"
    assert custom_node["ref_table"] == "clusters"


def test_impact_disclaimer_and_potentially_affected(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_cmdb_graph(client, auth_headers)
    impact = client.get(
        "/api/dependencies/dep10-db/impact?depth=5", headers=auth_headers
    )
    assert impact.status_code == 200, impact.text
    body = impact.json()
    assert body["disclaimer"] == IMPACT_DISCLAIMER
    assert "potentially affected" in body["disclaimer"].lower()
    apps = body["potentially_affected_applications"]
    assert any(a["component"]["component_id"] == "dep10-app" for a in apps)
    blob = str(body).lower()
    assert "is currently down" not in blob or "does not mean" in blob
    assert "is down" not in blob.replace("does not mean the application is currently down", "")

    bundle = client.get("/api/dependencies/dep10-db?depth=5", headers=auth_headers)
    assert bundle.status_code == 200
    assert bundle.json()["disclaimer"] == IMPACT_DISCLAIMER
    assert (
        bundle.json()["impact"]["disclaimer"] == IMPACT_DISCLAIMER
        or "potentially affected" in bundle.json()["impact"]["disclaimer"].lower()
    )


def test_max_dependency_depth_entitlement(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    ents = client.get("/api/entitlements", headers=auth_headers)
    assert ents.status_code == 200
    body = ents.json()
    assert body["billing_enabled"] is False
    assert body["limits"]["max_dependency_depth"] is None

    _seed_cmdb_graph(client, auth_headers)
    ok = client.get(
        "/api/dependencies/dep10-app/upstream?depth=5", headers=auth_headers
    )
    assert ok.status_code == 200

    with patch(
        "app.services.entitlements.max_dependency_depth", return_value=1
    ):
        blocked = client.get(
            "/api/dependencies/dep10-app/upstream?depth=5", headers=auth_headers
        )
        assert blocked.status_code == 403
        assert "depth" in blocked.text.lower()

        shallow = client.get(
            "/api/dependencies/dep10-app/upstream?depth=1", headers=auth_headers
        )
        assert shallow.status_code == 200


def test_dependencies_ui_markers_and_version(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    html = client.get("/", headers=auth_headers).text
    assert 'id="depComponentId"' in html
    assert 'id="depTable"' in html
    assert 'id="depEntityIdList"' in html
    assert 'id="depTableList"' in html
    assert "Source Table" in html
    assert "Target Table" in html
    assert "potentially affected" in html.lower()
    from app import __version__

    assert __version__ in html
    assert "max_dependency_depth" in html
    js = client.get("/static/js/cmdb.js", headers=auth_headers).text
    assert "syncDepPickers" in js
    assert "params.set(\"table\"" in js or "params.set('table'" in js
