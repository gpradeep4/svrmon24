"""API-backed user journey checks for Phase 8 screens (no browser)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_main_user_journey(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    # 1) Inventory create + detail
    created = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_id": "journey-srv",
            "component_type": "Server",
            "name": "journey-host",
            "environment": "prod",
            "status": "active",
            "hostname": "journey-host",
            "os_family": "RHEL",
            "os_version": "9.4",
        },
    )
    assert created.status_code == 201, created.text
    detail = client.get("/api/components/journey-srv", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["os_family"] == "RHEL"
    assert detail.json()["os_version"] == "9.4"

    app = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_id": "journey-app",
            "component_type": "Application",
            "name": "billing",
            "environment": "prod",
            "status": "active",
            "application_name": "Billing",
        },
    )
    assert app.status_code == 201, app.text

    # 2) Relationship management (separate protocol / ports)
    rel = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "relationship_id": "journey-rel",
            "relationship_type": "DEPENDS_ON",
            "source_component_id": "journey-app",
            "target_component_id": "journey-srv",
            "protocol": "HTTPS",
            "source_port": None,
            "target_port": 8443,
            "verification_status": "unverified",
        },
    )
    assert rel.status_code == 201, rel.text
    assert rel.json()["protocol"] == "HTTPS"
    assert rel.json()["target_port"] == 8443
    assert rel.json()["source_port"] is None

    # 3) Dependency graph + impact
    deps = client.get(
        "/api/dependencies/journey-srv?depth=5",
        headers=auth_headers,
    )
    assert deps.status_code == 200, deps.text
    body = deps.json()
    assert "graph" in body
    assert "upstream" in body and "downstream" in body
    assert "potentially_affected_applications" in (body.get("impact") or {})

    # 4) Diagnostic history + details
    diag = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={"component_id": "journey-srv", "profile_name": "basic-health"},
    )
    assert diag.status_code == 201, diag.text
    assert diag.json()["execution_mode"] == "SIMULATED"
    diag_id = diag.json()["diagnostic_id"]

    history = client.get("/api/diagnostics", headers=auth_headers)
    assert history.status_code == 200
    assert any(i["diagnostic_id"] == diag_id for i in history.json().get("items", []))

    # 5) AI analysis (force fallback — no Ollama required)
    analysis = client.post(
        f"/api/diagnostics/{diag_id}/analyze",
        headers=auth_headers,
        json={"force_fallback": True},
    )
    assert analysis.status_code == 200, analysis.text
    assert analysis.json()["ai_analysis"]["derived_from_simulated_data"] is True

    # 6) Dashboard live widgets
    dash = client.get("/api/dashboard/summary", headers=auth_headers)
    assert dash.status_code == 200, dash.text
    summary = dash.json()
    assert summary["total_components"] == 2
    assert summary["total_relationships"] == 1
    assert summary["components_by_type"]["Server"] == 1
    assert len(summary["recent_diagnostics"]) >= 1
    assert summary["labels"]["diagnostics_mode"] == "SIMULATED"

    # 7) UI shell still served
    ui = client.get("/")
    assert ui.status_code == 200
    assert b'data-tab="dashboard"' in ui.content
    assert b"OS Family" in ui.content
    assert b"Source Port" in ui.content
    assert b"SIMULATED" in ui.content
