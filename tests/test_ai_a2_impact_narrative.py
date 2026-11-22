"""AI A2 — CMDB impact narrative + change-risk assist (C3/C4)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def providers_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OLLAMA_ENABLED", "false")
    monkeypatch.setenv("AI_CLOUD_SUGGESTIONS_ENABLED", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _seed_topo(client: TestClient, headers: dict[str, str]) -> None:
    for body in (
        {
            "component_id": "srv-a2",
            "component_type": "Server",
            "name": "host-a2",
            "environment": "prod",
            "status": "active",
            "hostname": "host-a2",
            "os_family": "RHEL",
            "os_version": "9",
        },
        {
            "component_id": "mware-a2",
            "component_type": "Middleware",
            "name": "tomcat-a2",
            "environment": "prod",
            "status": "active",
            "product_type": "Tomcat",
        },
        {
            "component_id": "app-a2",
            "component_type": "Application",
            "name": "portal-a2",
            "environment": "prod",
            "status": "active",
            "application_name": "portal-a2",
            "service_url": "https://portal.example",
        },
    ):
        assert client.post("/api/components", headers=headers, json=body).status_code == 201
    for edge in (
        {
            "source_component_id": "mware-a2",
            "target_component_id": "srv-a2",
            "relationship_type": "HOSTED_ON",
        },
        {
            "source_component_id": "app-a2",
            "target_component_id": "mware-a2",
            "relationship_type": "DEPENDS_ON",
        },
    ):
        assert (
            client.post("/api/relationships", headers=headers, json=edge).status_code
            == 201
        )


def test_impact_narrative_fallback_uses_graph_ids(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _seed_topo(client, auth_headers)
    resp = client.post(
        "/api/dependencies/ai/impact-narrative",
        headers=auth_headers,
        json={"component_id": "srv-a2", "depth": 5, "force_fallback": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "rule_based_fallback"
    assert body["disclaimer"]
    assert "potentially" in (body["disclaimer"] or "").lower() or "not mean" in (
        body["disclaimer"] or ""
    ).lower()
    cited = set(body.get("cited_component_ids") or [])
    assert "srv-a2" in cited
    # Narrative / ranked apps must only reference graph ids
    for app in body.get("ranked_affected_apps") or []:
        assert app["component_id"] in cited
    assert "app-a2" in {
        a["component_id"] for a in (body.get("ranked_affected_apps") or [])
    }
    assert body["safety"]["invented_ids_forbidden"] is True
    assert body["safety"]["potential_impact_not_outage"] is True


def test_change_risk_fallback_band(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _seed_topo(client, auth_headers)
    resp = client.post(
        "/api/dependencies/ai/change-risk",
        headers=auth_headers,
        json={
            "component_ids": ["srv-a2"],
            "change_type": "normal",
            "force_fallback": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["risk_band"] in {"low", "medium", "high"}
    assert body["checklist"]
    assert body["safety"]["no_auto_cab"] is True
    for path in body.get("evidence_paths") or []:
        assert path["component_id"] in set(body.get("cited_component_ids") or [])


def test_invented_ids_stripped_from_model_output(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    from app.cmdb.services import ai_cmdb_assist as assist
    from app.services.ai_providers import SOURCE_OLLAMA

    _seed_topo(client, auth_headers)
    from app.cmdb.services import dependencies as deps

    impact = deps.analyze_impact("srv-a2", tenant_id="tenant-svrmon24-legacy", depth=5)
    normalized = assist._normalize_impact_narrative(
        {
            "executive_narrative": "Affects app-a2 and invented-x",
            "ranked_affected_apps": [
                {"component_id": "app-a2"},
                {"component_id": "invented-x"},
            ],
            "cited_component_ids": ["app-a2", "invented-x", "srv-a2"],
            "uncertainty": "test",
        },
        impact=impact,
        source=SOURCE_OLLAMA,
        model="test",
    )
    cited = set(normalized["cited_component_ids"])
    assert "invented-x" not in cited
    assert "app-a2" in cited
    assert all(
        a["component_id"] != "invented-x"
        for a in normalized["ranked_affected_apps"]
    )


def test_ui_markers_and_version(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from app import __version__

    assert __version__ == "0.79.0"
    html = client.get("/", headers=auth_headers).text
    assert 'id="btnImpactNarrative"' in html
    assert 'id="btnChangeRisk"' in html
    assert __version__ in html
    js = client.get("/static/js/cmdb.js", headers=auth_headers).text
    assert "/api/dependencies/ai/impact-narrative" in js
    assert "/api/dependencies/ai/change-risk" in js
