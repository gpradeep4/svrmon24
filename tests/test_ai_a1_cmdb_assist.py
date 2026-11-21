"""AI A1 — CMDB classification + relationship suggestions (assist only)."""

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


def _create_component(
    client: TestClient,
    headers: dict[str, str],
    *,
    cid: str,
    ctype: str,
    name: str,
    **extra,
) -> dict:
    body = {
        "component_id": cid,
        "component_type": ctype,
        "name": name,
        "environment": "prod",
        "status": "active",
        **extra,
    }
    resp = client.post("/api/components", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_classification_fallback_postgres(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    resp = client.post(
        "/api/components/ai/suggest-classification",
        headers=auth_headers,
        json={
            "draft": {
                "name": "orders-postgres",
                "product_type": "PostgreSQL",
                "endpoint": "db.example:5432",
            },
            "force_fallback": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "rule_based_fallback"
    assert body["suggested_component_type"] == "Database"
    assert body["safety"]["auto_apply"] is False
    assert body["safety"]["human_must_confirm"] is True
    assert "endpoint" in (body.get("suggested_fields") or {})


def test_classification_fallback_server_hostname(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    resp = client.post(
        "/api/components/ai/suggest-classification",
        headers=auth_headers,
        json={
            "draft": {
                "name": "app-host-01",
                "hostname": "app-host-01.example",
                "os_family": "RHEL",
                "os_version": "9",
            },
            "force_fallback": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggested_component_type"] == "Server"
    assert body["suggested_fields"].get("hostname") == "app-host-01.example"


def test_suggest_does_not_create_component(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    before = client.get("/api/components", headers=auth_headers).json()["total"]
    client.post(
        "/api/components/ai/suggest-classification",
        headers=auth_headers,
        json={"draft": {"name": "ghost-db", "product_type": "Oracle"}, "force_fallback": True},
    )
    after = client.get("/api/components", headers=auth_headers).json()["total"]
    assert after == before


def test_relationship_pair_fallback(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _create_component(
        client,
        auth_headers,
        cid="mware-a1",
        ctype="Middleware",
        name="tomcat-a",
        product_type="Tomcat",
    )
    _create_component(
        client,
        auth_headers,
        cid="srv-a1",
        ctype="Server",
        name="host-a",
        hostname="host-a",
        os_family="RHEL",
        os_version="9",
    )
    resp = client.post(
        "/api/relationships/ai/suggest",
        headers=auth_headers,
        json={
            "source_component_id": "mware-a1",
            "target_component_id": "srv-a1",
            "force_fallback": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "rule_based_fallback"
    pair = body["pair_suggestion"]
    assert pair["relationship_type"] == "HOSTED_ON"
    assert pair["verification_status"] == "unverified"
    assert pair["source_component_id"] == "mware-a1"
    assert pair["target_component_id"] == "srv-a1"
    assert body["safety"]["auto_apply"] is False


def test_relationship_neighbors_and_no_silent_create(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _create_component(
        client,
        auth_headers,
        cid="app-a1",
        ctype="Application",
        name="orders-api",
        application_name="orders-api",
        service_url="https://orders.example",
    )
    _create_component(
        client,
        auth_headers,
        cid="db-a1",
        ctype="Database",
        name="orders-db",
        product_type="PostgreSQL",
        endpoint="db:5432",
    )
    before = client.get("/api/relationships", headers=auth_headers).json()["total"]
    resp = client.post(
        "/api/relationships/ai/suggest",
        headers=auth_headers,
        json={"component_id": "app-a1", "force_fallback": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    neighbors = body.get("neighbor_suggestions") or []
    assert any(
        n.get("target_component_id") == "db-a1"
        or n.get("source_component_id") == "db-a1"
        for n in neighbors
    )
    after = client.get("/api/relationships", headers=auth_headers).json()["total"]
    assert after == before


def test_human_apply_still_uses_normal_create(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _create_component(
        client,
        auth_headers,
        cid="app-apply",
        ctype="Application",
        name="portal",
        application_name="portal",
    )
    _create_component(
        client,
        auth_headers,
        cid="db-apply",
        ctype="Database",
        name="portal-db",
        product_type="MySQL",
        endpoint="mysql:3306",
    )
    suggest = client.post(
        "/api/relationships/ai/suggest",
        headers=auth_headers,
        json={
            "source_component_id": "app-apply",
            "target_component_id": "db-apply",
            "force_fallback": True,
        },
    ).json()
    pair = suggest["pair_suggestion"]
    created = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": pair["source_component_id"],
            "target_component_id": pair["target_component_id"],
            "relationship_type": pair["relationship_type"],
            "verification_status": "unverified",
            "discovery_method": "discovered",
            "confidence": "low",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["verification_status"] == "unverified"


def test_ui_markers_and_version(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from app import __version__

    assert __version__ == "0.54.0"
    html = client.get("/", headers=auth_headers).text
    assert 'id="btnSuggestClassification"' in html
    assert 'id="btnSuggestRelationship"' in html
    assert __version__ in html
    js = client.get("/static/js/cmdb.js", headers=auth_headers).text
    assert "/api/components/ai/suggest-classification" in js
    assert "/api/relationships/ai/suggest" in js
