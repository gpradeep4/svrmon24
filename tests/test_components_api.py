"""CMDB component API tests (CRUD, search, pagination, delete confirmation)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _server_payload(**overrides):
    base = {
        "component_id": "srv-web01",
        "component_type": "Server",
        "name": "web-01",
        "environment": "prod",
        "status": "active",
        "hostname": "web-01.example.com",
        "ip_address": "10.0.0.11",
        "os_family": "RHEL",
        "os_version": "9.4",
    }
    base.update(overrides)
    return base


def test_components_require_auth(client: TestClient) -> None:
    response = client.get("/api/components")
    assert response.status_code == 401


def test_create_get_update_delete_component(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post("/api/components", headers=auth_headers, json=_server_payload())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["component_id"] == "srv-web01"
    assert body["os_family"] == "RHEL"
    assert body["os_version"] == "9.4"

    fetched = client.get("/api/components/srv-web01", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["hostname"] == "web-01.example.com"

    updated = client.put(
        "/api/components/srv-web01",
        headers=auth_headers,
        json={"os_version": "9.5", "status": "inactive"},
    )
    assert updated.status_code == 200
    assert updated.json()["os_version"] == "9.5"
    assert updated.json()["status"] == "inactive"

    # delete without confirmation rejected
    denied = client.delete("/api/components/srv-web01", headers=auth_headers)
    assert denied.status_code == 400

    preview = client.get("/api/components/srv-web01/delete-preview", headers=auth_headers)
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    assert preview.json()["relationship_warning"]["engine_ready"] is True
    assert preview.json()["relationship_warning"]["has_relationships"] is False

    deleted = client.delete(
        "/api/components/srv-web01?confirmed=true", headers=auth_headers
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    missing = client.get("/api/components/srv-web01", headers=auth_headers)
    assert missing.status_code == 404


def test_duplicate_component_id_conflict(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    assert client.post("/api/components", headers=auth_headers, json=_server_payload()).status_code == 201
    again = client.post("/api/components", headers=auth_headers, json=_server_payload())
    assert again.status_code == 409


def test_list_search_filter_pagination(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    payloads = [
        _server_payload(component_id="srv-a", name="alpha", hostname="alpha", environment="prod"),
        _server_payload(
            component_id="srv-b",
            name="beta",
            hostname="beta",
            environment="nonprod",
            os_family="Windows",
            os_version="2022",
        ),
        {
            "component_id": "mware-1",
            "component_type": "Middleware",
            "name": "wls",
            "environment": "prod",
            "product_type": "WebLogic",
            "product_version": "14.1.1",
            "listen_port": 7001,
        },
    ]
    for payload in payloads:
        assert client.post("/api/components", headers=auth_headers, json=payload).status_code == 201

    listed = client.get("/api/components?page=1&page_size=2", headers=auth_headers)
    assert listed.status_code == 200
    data = listed.json()
    assert data["total"] == 3
    assert data["page_size"] == 2
    assert len(data["items"]) == 2
    assert len(data["inventory"]) == 2
    # inventory columns present and separate
    row = data["inventory"][0]
    for key in (
        "component_id",
        "hostname_or_name",
        "component_type",
        "os_family",
        "os_version",
        "product_type",
        "product_version",
        "environment",
        "status",
    ):
        assert key in row

    filtered = client.get(
        "/api/components?component_type=Server&environment=prod",
        headers=auth_headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["component_id"] == "srv-a"

    searched = client.get("/api/components?q=WebLogic", headers=auth_headers)
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    inv = searched.json()["inventory"][0]
    assert inv["product_type"] == "WebLogic"
    assert inv["product_version"] == "14.1.1"
    assert inv["os_family"] == "—"
    assert inv["os_version"] == "—"


def test_auto_generates_component_id(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    payload = _server_payload()
    del payload["component_id"]
    response = client.post("/api/components", headers=auth_headers, json=payload)
    assert response.status_code == 201
    assert response.json()["component_id"].startswith("srv-")


def test_ui_index_is_public(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "SVRMON24" in response.text
    assert "OS Family" in response.text
    assert "OS Version" in response.text
    assert "Product Type" in response.text
    assert "Product Version" in response.text
