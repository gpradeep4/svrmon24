"""Relationship API tests — IDs, duplicates, ports, updates."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _seed_components(client: TestClient, headers: dict[str, str]) -> None:
    payloads = [
        {
            "component_id": "srv-1",
            "component_type": "Server",
            "name": "app-host",
            "environment": "prod",
            "hostname": "app-host",
            "os_family": "RHEL",
            "os_version": "9.4",
        },
        {
            "component_id": "srv-2",
            "component_type": "Server",
            "name": "db-host",
            "environment": "nonprod",
            "hostname": "db-host",
            "os_family": "RHEL",
            "os_version": "8.9",
        },
        {
            "component_id": "mware-1",
            "component_type": "Middleware",
            "name": "wls-a",
            "environment": "prod",
            "product_type": "WebLogic",
            "product_version": "14.1.1",
        },
        {
            "component_id": "mware-2",
            "component_type": "Middleware",
            "name": "wls-b",
            "environment": "prod",
            "product_type": "WebLogic",
            "product_version": "14.1.1",
        },
        {
            "component_id": "db-1",
            "component_type": "Database",
            "name": "oracle-1",
            "environment": "prod",
            "product_type": "Oracle",
            "product_version": "19c",
        },
    ]
    for payload in payloads:
        assert client.post("/api/components", headers=headers, json=payload).status_code == 201


def test_relationships_require_auth(client: TestClient) -> None:
    assert client.get("/api/relationships").status_code == 401


def test_invalid_component_ids_rejected(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_components(client, auth_headers)
    response = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "mware-1",
            "target_component_id": "srv-missing",
            "relationship_type": "HOSTED_ON",
        },
    )
    assert response.status_code == 422
    assert "does not exist" in response.text


def test_self_reference_rejected(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_components(client, auth_headers)
    response = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "srv-1",
            "target_component_id": "srv-1",
            "relationship_type": "DEPENDS_ON",
        },
    )
    assert response.status_code == 422


def test_duplicate_relationships_rejected(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_components(client, auth_headers)
    payload = {
        "source_component_id": "mware-1",
        "target_component_id": "srv-1",
        "relationship_type": "HOSTED_ON",
        "protocol": None,
        "source_port": None,
        "target_port": None,
    }
    first = client.post("/api/relationships", headers=auth_headers, json=payload)
    assert first.status_code == 201, first.text
    second = client.post("/api/relationships", headers=auth_headers, json=payload)
    assert second.status_code == 409


def test_blank_ports_allowed(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_components(client, auth_headers)
    response = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "mware-1",
            "target_component_id": "srv-1",
            "relationship_type": "HOSTED_ON",
            "source_port": None,
            "target_port": None,
            "discovery_method": "manually_configured",
            "verification_status": "unverified",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_port"] is None
    assert body["target_port"] is None


def test_valid_ports_stored_independently(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_components(client, auth_headers)
    response = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "mware-1",
            "target_component_id": "db-1",
            "relationship_type": "CONNECTS_TO",
            "protocol": "TCP",
            "source_port": 45000,
            "target_port": 1521,
            "discovery_method": "manually_configured",
            "verification_status": "verified",
            "confidence": "high",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["protocol"] == "TCP"
    assert body["source_port"] == 45000
    assert body["target_port"] == 1521
    assert body["source_port"] != body["target_port"]

    listed = client.get("/api/relationships", headers=auth_headers)
    assert listed.status_code == 200
    row = listed.json()["rows"][0]
    assert row["protocol"] == "TCP"
    assert row["source_port"] == "45000"
    assert row["target_port"] == "1521"
    assert "source_port" in row and "target_port" in row
    assert "ports" not in row


def test_invalid_ports_rejected(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_components(client, auth_headers)
    for bad in (0, 65536, -1, "abc"):
        response = client.post(
            "/api/relationships",
            headers=auth_headers,
            json={
                "source_component_id": "mware-1",
                "target_component_id": "db-1",
                "relationship_type": "CONNECTS_TO",
                "source_port": bad,
                "target_port": 1521,
            },
        )
        assert response.status_code == 422, bad


def test_relationship_update(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_components(client, auth_headers)
    created = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "relationship_id": "rel-update-1",
            "source_component_id": "mware-1",
            "target_component_id": "db-1",
            "relationship_type": "CONNECTS_TO",
            "protocol": "TCP",
            "source_port": 4000,
            "target_port": 1521,
            "verification_status": "unverified",
        },
    )
    assert created.status_code == 201, created.text

    updated = client.put(
        "/api/relationships/rel-update-1",
        headers=auth_headers,
        json={
            "target_port": 1522,
            "verification_status": "verified",
            "confidence": "high",
            "evidence_or_notes": "Checked in change ticket CHG-1",
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["source_port"] == 4000  # unchanged, independent
    assert body["target_port"] == 1522
    assert body["verification_status"] == "verified"
    assert body["evidence_or_notes"] == "Checked in change ticket CHG-1"

    fetched = client.get("/api/relationships/rel-update-1", headers=auth_headers)
    assert fetched.json()["target_port"] == 1522


def test_multiple_hosted_on_same_server(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_components(client, auth_headers)
    for mware in ("mware-1", "mware-2"):
        response = client.post(
            "/api/relationships",
            headers=auth_headers,
            json={
                "source_component_id": mware,
                "target_component_id": "srv-1",
                "relationship_type": "HOSTED_ON",
                "discovery_method": "manually_configured",
            },
        )
        assert response.status_code == 201, response.text

    listed = client.get(
        "/api/relationships?target_component_id=srv-1&relationship_type=HOSTED_ON",
        headers=auth_headers,
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 2


def test_environment_mismatch_warning(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_components(client, auth_headers)
    response = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "mware-1",  # prod
            "target_component_id": "srv-2",  # nonprod
            "relationship_type": "HOSTED_ON",
        },
    )
    assert response.status_code == 201
    assert "warnings" in response.json()
    assert response.json()["warnings"][0]["code"] == "environment_mismatch"


def test_delete_preview_warns_when_relationships_exist(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_components(client, auth_headers)
    assert (
        client.post(
            "/api/relationships",
            headers=auth_headers,
            json={
                "source_component_id": "mware-1",
                "target_component_id": "srv-1",
                "relationship_type": "HOSTED_ON",
            },
        ).status_code
        == 201
    )
    preview = client.get("/api/components/srv-1/delete-preview", headers=auth_headers)
    assert preview.status_code == 200
    warning = preview.json()["relationship_warning"]
    assert warning["has_relationships"] is True
    assert warning["relationship_count"] == 1
    assert warning["engine_implemented"] is True


def test_relationship_types_documented(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/relationships/types", headers=auth_headers)
    assert response.status_code == 200
    types = {item["relationship_type"]: item for item in response.json()["types"]}
    for key in ("HOSTED_ON", "DEPENDS_ON", "CONNECTS_TO", "ROUTES_TO"):
        assert key in types
        assert "direction" in types[key]
        assert "meaning" in types[key]
