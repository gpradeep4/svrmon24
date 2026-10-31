"""Dashboard summary API — live aggregates (no hardcoded counts)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _seed_server(client: TestClient, headers: dict, **overrides) -> None:
    payload = {
        "component_id": "dash-srv",
        "component_type": "Server",
        "name": "dash-host",
        "environment": "prod",
        "status": "active",
        "hostname": "dash-host",
        "os_family": "RHEL",
        "os_version": "9",
    }
    payload.update(overrides)
    assert client.post("/api/components", headers=headers, json=payload).status_code == 201


def test_dashboard_summary_empty(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    response = client.get("/api/dashboard/summary", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_components"] == 0
    assert body["total_relationships"] == 0
    assert body["components_by_type"] == {}
    assert body["components_by_environment"] == {}
    assert body["recent_diagnostics"] == []
    assert body["recent_findings"] == []
    assert body["critical_components_requiring_review"] == []
    assert body["labels"]["diagnostics_mode"] == "SIMULATED"


def test_dashboard_summary_live_counts(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_server(client, auth_headers, component_id="srv-a", environment="prod")
    assert (
        client.post(
            "/api/components",
            headers=auth_headers,
            json={
                "component_id": "app-b",
                "component_type": "Application",
                "name": "app-b",
                "environment": "nonprod",
                "status": "inactive",
                "application_name": "Billing",
                "application_type": "WebApp",
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/relationships",
            headers=auth_headers,
            json={
                "relationship_id": "rel-dash-1",
                "relationship_type": "DEPENDS_ON",
                "source_component_id": "app-b",
                "target_component_id": "srv-a",
                "protocol": "TCP",
                "source_port": None,
                "target_port": 443,
                "verification_status": "unverified",
            },
        ).status_code
        == 201
    )
    diag = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={"component_id": "srv-a", "profile_name": "basic-health"},
    )
    assert diag.status_code == 201, diag.text

    response = client.get("/api/dashboard/summary?recent_limit=5", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_components"] == 2
    assert body["total_relationships"] == 1
    assert body["components_by_type"]["Server"] == 1
    assert body["components_by_type"]["Application"] == 1
    assert body["components_by_environment"]["prod"] == 1
    assert body["components_by_environment"]["nonprod"] == 1
    assert len(body["recent_diagnostics"]) >= 1
    assert body["recent_diagnostics"][0]["execution_mode"] == "SIMULATED"
    # inactive + unverified relationship → review list
    review_ids = {
        row["component_id"] for row in body["critical_components_requiring_review"]
    }
    assert "app-b" in review_ids
    assert "SIMULATED" in body["labels"]["findings_banner"]


def test_dashboard_requires_auth(client: TestClient, clean_db) -> None:
    assert client.get("/api/dashboard/summary").status_code == 401


def test_ui_contains_dashboard_and_required_columns() -> None:
    """Static UI smoke: required screens/columns present (no browser)."""
    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    css = (root / "app" / "static" / "css" / "cmdb.css").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "js" / "cmdb.js").read_text(encoding="utf-8")

    assert 'data-tab="dashboard"' in html
    assert 'id="tab-dashboard"' in html
    assert "OS Family" in html and "OS Version" in html
    assert "Product Type" in html and "Product Version" in html
    assert "Protocol" in html and "Source Port" in html and "Target Port" in html
    assert "SIMULATED" in html
    assert "loadDashboard" in js
    assert "/api/dashboard/summary" in js
    assert ".dash-grid" in css or "dash-grid" in css
    for screen in (
        "tab-inventory",
        "tab-relationships",
        "tab-dependencies",
        "tab-diagnostics",
        "componentModal",
        "relationshipModal",
    ):
        assert screen in html
