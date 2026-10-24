"""Dependency traversal and impact analysis tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create_component(client: TestClient, headers: dict, **payload):
    response = client.post("/api/components", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _link(
    client: TestClient,
    headers: dict,
    *,
    source: str,
    target: str,
    rtype: str,
    protocol: str | None = None,
    source_port: int | None = None,
    target_port: int | None = None,
    relationship_id: str | None = None,
):
    body = {
        "source_component_id": source,
        "target_component_id": target,
        "relationship_type": rtype,
        "protocol": protocol,
        "source_port": source_port,
        "target_port": target_port,
        "discovery_method": "manually_configured",
        "verification_status": "verified",
        "evidence_or_notes": "seeded for traversal tests",
    }
    if relationship_id:
        body["relationship_id"] = relationship_id
    response = client.post("/api/relationships", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _seed_multi_tier(client: TestClient, headers: dict) -> None:
    """
    app-1 DEPENDS_ON mware-1 HOSTED_ON srv-1
    mware-1 CONNECTS_TO db-1
    app-1 DEPENDS_ON db-1  (shared / multiple paths to db)
    """
    _create_component(
        client,
        headers,
        component_id="srv-1",
        component_type="Server",
        name="host",
        environment="prod",
        status="active",
        hostname="host",
        os_family="RHEL",
        os_version="9",
    )
    _create_component(
        client,
        headers,
        component_id="mware-1",
        component_type="Middleware",
        name="wls",
        environment="prod",
        status="active",
        product_type="WebLogic",
        product_version="14",
    )
    _create_component(
        client,
        headers,
        component_id="db-1",
        component_type="Database",
        name="oracle",
        environment="prod",
        status="active",
        product_type="Oracle",
        product_version="19c",
    )
    _create_component(
        client,
        headers,
        component_id="app-1",
        component_type="Application",
        name="portal",
        environment="prod",
        status="active",
        application_name="portal",
    )
    _link(client, headers, source="mware-1", target="srv-1", rtype="HOSTED_ON", relationship_id="rel-host")
    _link(
        client,
        headers,
        source="mware-1",
        target="db-1",
        rtype="CONNECTS_TO",
        protocol="TCP",
        source_port=45000,
        target_port=1521,
        relationship_id="rel-jdbc",
    )
    _link(client, headers, source="app-1", target="mware-1", rtype="DEPENDS_ON", relationship_id="rel-app-mw")
    _link(client, headers, source="app-1", target="db-1", rtype="DEPENDS_ON", relationship_id="rel-app-db")


def test_upstream_multi_tier(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_multi_tier(client, auth_headers)
    response = client.get(
        "/api/dependencies/app-1/upstream?depth=5",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["selected"]["component_id"] == "app-1"
    ids = {n["component_id"] for n in data["nodes"]}
    assert {"app-1", "mware-1", "db-1", "srv-1"} <= ids

    # Ports stay separate on edges/rows
    jdbc = next(e for e in data["edges"] if e["relationship_id"] == "rel-jdbc")
    assert jdbc["protocol"] == "TCP"
    assert jdbc["source_port"] == 45000
    assert jdbc["target_port"] == 1521
    assert "ports" not in jdbc

    direct = [n for n in data["nodes"] if n.get("direct") and not n.get("is_selected")]
    assert {n["component_id"] for n in direct} == {"mware-1", "db-1"}


def test_downstream_and_impact(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_multi_tier(client, auth_headers)
    down = client.get("/api/dependencies/db-1/downstream?depth=5", headers=auth_headers)
    assert down.status_code == 200
    down_ids = {n["component_id"] for n in down.json()["nodes"]}
    assert "app-1" in down_ids
    assert "mware-1" in down_ids

    impact = client.get("/api/dependencies/db-1/impact?depth=5", headers=auth_headers)
    assert impact.status_code == 200
    body = impact.json()
    assert "potentially affected" in body["disclaimer"].lower() or "Potentially" in body["disclaimer"]
    apps = body["potentially_affected_applications"]
    assert len(apps) == 1
    assert apps[0]["component"]["component_id"] == "app-1"
    assert "connecting_paths" in apps[0]
    assert "not mean the application is currently down" in apps[0]["note"]
    # Must not claim actual outage
    blob = str(body).lower()
    assert "is down" not in blob
    assert "is currently down" not in blob or "does not mean" in blob


def test_multiple_paths(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_multi_tier(client, auth_headers)
    response = client.get(
        "/api/dependencies/app-1/upstream?depth=5",
        headers=auth_headers,
    )
    paths = response.json()["paths"]
    db_paths = [p for p in paths if p["component_ids"][-1] == "db-1"]
    # Direct app→db and app→mware→db
    assert len(db_paths) >= 2
    shapes = {tuple(p["component_ids"]) for p in db_paths}
    assert ("app-1", "db-1") in shapes
    assert ("app-1", "mware-1", "db-1") in shapes


def test_cycle_detection(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _create_component(
        client, auth_headers,
        component_id="a", component_type="Application", name="a",
        environment="prod", status="active", application_name="a",
    )
    _create_component(
        client, auth_headers,
        component_id="b", component_type="Application", name="b",
        environment="prod", status="active", application_name="b",
    )
    _link(client, auth_headers, source="a", target="b", rtype="DEPENDS_ON")
    _link(client, auth_headers, source="b", target="a", rtype="DEPENDS_ON")

    response = client.get("/api/dependencies/a/upstream?depth=5", headers=auth_headers)
    assert response.status_code == 200
    cycles = response.json()["cycles_detected"]
    assert len(cycles) >= 1
    assert any(c["closed_at"] == "a" or "a" in c["component_ids"] for c in cycles)


def test_depth_limit(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_multi_tier(client, auth_headers)
    shallow = client.get(
        "/api/dependencies/app-1/upstream?depth=1",
        headers=auth_headers,
    )
    assert shallow.status_code == 200
    ids = {n["component_id"] for n in shallow.json()["nodes"] if not n.get("is_selected")}
    assert ids == {"mware-1", "db-1"}
    assert "srv-1" not in ids

    deeper = client.get(
        "/api/dependencies/app-1/upstream?depth=2",
        headers=auth_headers,
    )
    deeper_ids = {n["component_id"] for n in deeper.json()["nodes"]}
    assert "srv-1" in deeper_ids


def test_missing_component_endpoint(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    response = client.get(
        "/api/dependencies/does-not-exist/upstream",
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_missing_related_component_reported(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _create_component(
        client, auth_headers,
        component_id="app-x", component_type="Application", name="x",
        environment="prod", status="active", application_name="x",
    )
    # Insert orphan relationship directly (simulates deleted component left dangling)
    from app.db import get_database
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    get_database()["cmdb_relationships"].insert_one(
        {
            "relationship_id": "rel-orphan",
            "source_component_id": "app-x",
            "target_component_id": "gone-db",
            "relationship_type": "DEPENDS_ON",
            "protocol": None,
            "source_port": None,
            "target_port": None,
            "discovery_method": "manually_configured",
            "verification_status": "unverified",
            "confidence": "low",
            "duplicate_key": "app-x|gone-db|DEPENDS_ON|||",
            "created_at": now,
            "updated_at": now,
        }
    )
    response = client.get("/api/dependencies/app-x/upstream?depth=3", headers=auth_headers)
    assert response.status_code == 200
    assert "gone-db" in response.json()["missing_components"]


def test_environment_and_status_filters(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_multi_tier(client, auth_headers)
    _create_component(
        client, auth_headers,
        component_id="db-np", component_type="Database", name="npdb",
        environment="nonprod", status="inactive",
        product_type="Oracle", product_version="19c",
    )
    _link(client, auth_headers, source="app-1", target="db-np", rtype="DEPENDS_ON")

    filtered = client.get(
        "/api/dependencies/app-1/upstream?depth=3&environment=prod&status=active",
        headers=auth_headers,
    )
    assert filtered.status_code == 200
    ids = {n["component_id"] for n in filtered.json()["nodes"]}
    assert "db-np" not in ids
    assert "db-1" in ids


def test_bundle_and_ui_columns(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_multi_tier(client, auth_headers)
    response = client.get("/api/dependencies/srv-1?depth=5", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert "upstream" in body and "downstream" in body and "impact" in body
    assert "graph" in body
    assert body["graph"]["nodes"] and body["graph"]["edges"] is not None
    row = body["downstream"]["rows"][0]
    for key in (
        "relationship_type",
        "protocol",
        "source_port",
        "target_port",
        "verification_status",
        "evidence_or_notes",
        "direct_or_indirect",
    ):
        assert key in row
    assert "ports" not in row


def test_dependencies_require_auth(client: TestClient) -> None:
    assert client.get("/api/dependencies/app-1/upstream").status_code == 401
