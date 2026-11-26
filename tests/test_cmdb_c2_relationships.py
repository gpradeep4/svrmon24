"""CMDB C2 — HOSTS + direction filters + Relationship Details (0.99.6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from tests.frontend_paths import FRONTEND_INDEX

REPO = Path(__file__).resolve().parents[1]
CI_DETAIL_JS = REPO / "frontend" / "static" / "js" / "cmdb" / "ci-detail.js"
CMDB_JS = REPO / "frontend" / "static" / "js" / "cmdb.js"
CMDB_CSS = REPO / "frontend" / "static" / "css" / "cmdb.css"


def test_c2_version_bump() -> None:
    assert __version__ == "0.99.6"


def test_frontend_c2_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.6"' in html
    assert "cmdb/ci-detail.js?v=0.99.6" in html

    js = CI_DETAIL_JS.read_text(encoding="utf-8")
    assert 'id: "relationships", label: "Relationships", active: true' in js
    assert 'id: "relationship-details", label: "Relationship Details", active: true' in js
    assert "HOSTS" in js
    assert "/api/components/" in js and "relationship-details" in js
    assert "direction=child" in js or 'direction", state.relDirection' in js
    assert "Create IP child" in js
    assert "ci-rel-tree" in js or "ciRelTree" in js
    # ITSM couple includes child CIs via API filter (no Mongo joins)
    assert "incl. " in js or "child CI" in js
    assert "/api/itsm/incidents?component_id=" in js

    cmdb = CMDB_JS.read_text(encoding="utf-8")
    assert "openRelCreatePrefill" in cmdb
    assert "SVRMON24Cmdb" in cmdb

    css = CMDB_CSS.read_text(encoding="utf-8")
    assert ".ci-rel-details" in css
    assert ".ci-rel-tree" in css


def test_hosts_in_relationship_type_catalog(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/relationships/types", headers=auth_headers)
    assert response.status_code == 200
    types = {item["relationship_type"]: item for item in response.json()["types"]}
    assert "HOSTS" in types
    for key in ("HOSTED_ON", "DEPENDS_ON", "CONNECTS_TO", "ROUTES_TO", "HOSTS"):
        assert key in types
        assert "direction" in types[key]
        assert "meaning" in types[key]


def _create_server(client: TestClient, headers: dict[str, str], name: str) -> str:
    created = client.post(
        "/api/components",
        headers=headers,
        json={
            "component_type": "Server",
            "name": name,
            "hostname": name,
            "environment": "Development",
            "status": "active",
            "os_family": "Linux",
            "os_version": "8.9",
            "ip_address": "10.9.9.1",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["component_id"]


def test_hosts_edge_direction_filters_and_relationship_details(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    srv = _create_server(client, auth_headers, "c2-hosts-srv.example.com")

    ip = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Network",
            "name": "IP 10.9.9.50",
            "environment": "Development",
            "status": "active",
            "device_type": "ip_endpoint",
            "management_ip": "10.9.9.50",
        },
    )
    assert ip.status_code == 201, ip.text
    ip_id = ip.json()["component_id"]

    soft = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Middleware",
            "name": "BigFix Agent",
            "environment": "Development",
            "status": "active",
            "product_type": "agent",
            "product_version": "11.0",
            "instance_name": "BigFix Agent",
        },
    )
    assert soft.status_code == 201, soft.text
    soft_id = soft.json()["component_id"]

    for target in (ip_id, soft_id):
        rel = client.post(
            "/api/relationships",
            headers=auth_headers,
            json={
                "source_component_id": srv,
                "target_component_id": target,
                "relationship_type": "HOSTS",
            },
        )
        assert rel.status_code == 201, rel.text
        assert rel.json()["relationship_type"] == "HOSTS"

    # Also keep legacy HOSTED_ON (middleware hosted on server) as child-of-server.
    mware = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Middleware",
            "name": "legacy-mware",
            "environment": "Development",
            "status": "active",
            "product_type": "tomcat",
            "product_version": "9",
        },
    )
    assert mware.status_code == 201, mware.text
    mware_id = mware.json()["component_id"]
    hosted = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": mware_id,
            "target_component_id": srv,
            "relationship_type": "HOSTED_ON",
        },
    )
    assert hosted.status_code == 201, hosted.text

    child_hosts = client.get(
        f"/api/relationships?component_id={srv}&direction=child&relationship_type=HOSTS&enrich=true",
        headers=auth_headers,
    )
    assert child_hosts.status_code == 200, child_hosts.text
    body = child_hosts.json()
    assert body["total"] == 2
    related = {i["related_component_id"] for i in body["items"]}
    assert related == {ip_id, soft_id}
    assert all(i.get("related_component") for i in body["items"])

    child_all = client.get(
        f"/api/relationships?component_id={srv}&direction=child&enrich=true",
        headers=auth_headers,
    )
    assert child_all.status_code == 200
    child_types = {i["relationship_type"] for i in child_all.json()["items"]}
    assert "HOSTS" in child_types
    assert "HOSTED_ON" in child_types
    child_related = {i["related_component_id"] for i in child_all.json()["items"]}
    assert ip_id in child_related and soft_id in child_related and mware_id in child_related

    parent_from_ip = client.get(
        f"/api/relationships?component_id={ip_id}&direction=parent&relationship_type=HOSTS",
        headers=auth_headers,
    )
    assert parent_from_ip.status_code == 200
    assert parent_from_ip.json()["total"] == 1
    assert parent_from_ip.json()["items"][0]["source_component_id"] == srv

    # direction without component_id → 422
    bad = client.get("/api/relationships?direction=child", headers=auth_headers)
    assert bad.status_code == 422

    details = client.get(
        f"/api/components/{srv}/relationship-details", headers=auth_headers
    )
    assert details.status_code == 200, details.text
    payload = details.json()
    assert payload["component_id"] == srv
    assert payload["primary_ip_address"] == "10.9.9.1"
    assert "tree" in payload and "groups" in payload
    groups = payload["groups"]
    assert groups["ip_endpoint"]["total"] >= 1
    assert any(it["component_id"] == ip_id for it in groups["ip_endpoint"]["items"])
    assert groups["product"]["total"] >= 1
    # Synthetic OS node from Server os_*
    assert groups["operating_system"]["total"] >= 1
    assert any(
        it.get("synthetic") for it in groups["operating_system"]["items"]
    )
    assert ip_id in payload["related_component_ids"]
    assert soft_id in payload["related_component_ids"]


def test_itsm_tickets_on_child_ci_via_api_filter(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    """Tight couple: INC on child IP is discoverable via ITSM API (not CMDB store)."""
    srv = _create_server(client, auth_headers, "c2-itsm-srv.example.com")
    ip = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Network",
            "name": "IP child for ITSM",
            "environment": "Development",
            "status": "active",
            "device_type": "ip_endpoint",
            "management_ip": "10.8.8.8",
        },
    )
    assert ip.status_code == 201, ip.text
    ip_id = ip.json()["component_id"]

    rel = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": srv,
            "target_component_id": ip_id,
            "relationship_type": "HOSTS",
        },
    )
    assert rel.status_code == 201, rel.text

    inc = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "C2 child IP incident",
            "priority": "p3",
            "ci_links": [{"component_id": ip_id}],
        },
    )
    assert inc.status_code == 201, inc.text

    # Parent alone may not see it; child component_id filter does.
    on_parent = client.get(
        f"/api/itsm/incidents?component_id={srv}&limit=5", headers=auth_headers
    )
    assert on_parent.status_code == 200
    parent_titles = [i["title"] for i in on_parent.json()["items"]]
    assert "C2 child IP incident" not in parent_titles

    on_child = client.get(
        f"/api/itsm/incidents?component_id={ip_id}&limit=5", headers=auth_headers
    )
    assert on_child.status_code == 200
    assert any(i["title"] == "C2 child IP incident" for i in on_child.json()["items"])

    # Relationship-details exposes child ids for the UI to query ITSM per child.
    details = client.get(
        f"/api/components/{srv}/relationship-details", headers=auth_headers
    )
    assert details.status_code == 200
    assert ip_id in details.json()["related_component_ids"]


@pytest.mark.parametrize(
    "path",
    [
        "frontend/static/js/cmdb/ci-detail.js",
        "frontend/static/css/cmdb.css",
    ],
)
def test_c2_assets_exist(path: str) -> None:
    assert (REPO / path).is_file()
