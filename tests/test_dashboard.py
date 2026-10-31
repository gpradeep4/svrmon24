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
    assert "sidebar" in html or "nav-item" in html
    assert "tenantSwitcher" in html
    assert "Not functional" in html or "placeholder" in html.lower()
    assert "--accent" in css and "#4F46E5" in css
    assert "--accent-hover" in css
    assert "svrmon24.accent" in js
    assert 'id="accentPicker"' in html or 'id="accentSelect"' in html
    assert "#2563EB" in html and "#0D9488" in html and "#475569" in html and "#7C3AED" in html
    assert "--sidebar-bg" in css
    assert "--sidebar-border" in css
    assert "#0F172A" in css and "#1E1B4B" in css
    assert "#0B3B44" not in css and "#0A333B" not in css
    assert "sidebarBg" in js and "--sidebar-bg" in js
    assert "#EEF1F4" in css and "#FFFFFF" in css
    assert "fonts.googleapis.com" not in html
    assert 'data-tab="servers"' in html
    assert 'data-tab="network"' in html
    assert 'data-tab="applications"' in html
    assert 'data-tab="middleware"' in html
    assert 'data-tab="databases"' in html
    assert 'data-component-type="Server"' in html
    assert "INVENTORY_TABS" in js
    assert "Column Settings" in html
    assert "Roles and Permissions" in html
    assert "Audit Logs" in html
    assert "Notifications" in html and "Placeholder" in html
    for screen in (
        "tab-inventory",
        "tab-relationships",
        "tab-dependencies",
        "tab-diagnostics",
        "tab-users",
        "tab-settings",
        "tab-columns",
        "tab-roles",
        "tab-organizations",
        "tab-plans",
        "tab-audit",
        "componentModal",
        "relationshipModal",
    ):
        assert screen in html
