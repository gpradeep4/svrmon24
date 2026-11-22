"""AI A4 — similar tickets + KB suggest (assist only, no auto-link)."""

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


def _create_incident(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str,
    description: str,
    category: str | None = None,
    priority: str = "p3",
    status: str = "new",
) -> dict:
    payload: dict = {
        "title": title,
        "description": description,
        "priority": priority,
        "status": status,
    }
    if category:
        payload["category"] = category
    resp = client.post("/api/itsm/incidents", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _resolve(client: TestClient, headers: dict[str, str], incident_id: str) -> None:
    for status in ("in_progress", "resolved"):
        body: dict = {"status": status}
        if status == "resolved":
            body["resolution_notes"] = "Fixed in lab"
            body["comment"] = "Closing"
        r = client.post(
            f"/api/itsm/incidents/{incident_id}/transition",
            headers=headers,
            json=body,
        )
        assert r.status_code == 200, r.text


def test_similar_finds_resolved_and_kb(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    prior = _create_incident(
        client,
        auth_headers,
        title="VPN gateway outage for remote users",
        description="Edge VPN tunnels down; network firewall rules checked",
        category="network",
    )
    _resolve(client, auth_headers, prior["incident_id"])

    kb = client.post(
        "/api/itsm/knowledge/articles",
        headers=auth_headers,
        json={
            "title": "Restart edge VPN gateway",
            "body": "Drain traffic then restart VPN service on the gateway.",
            "status": "draft",
            "category": "network",
            "tags": ["vpn", "gateway", "outage"],
        },
    )
    assert kb.status_code == 201, kb.text
    article_id = kb.json()["article_id"]
    pub = client.post(
        f"/api/itsm/knowledge/articles/{article_id}/transition",
        headers=auth_headers,
        json={"status": "published"},
    )
    assert pub.status_code == 200, pub.text

    current = _create_incident(
        client,
        auth_headers,
        title="VPN intermittent for remote users",
        description="Network VPN drops; firewall path suspected",
        category="network",
    )
    resp = client.post(
        f"/api/itsm/incidents/{current['incident_id']}/ai/similar",
        headers=auth_headers,
        json={"force_fallback": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "rule_based_fallback"
    assert body["safety"]["no_auto_link"] is True
    assert body["safety"]["auto_link"] is False
    ticket_ids = {t["ticket_id"] for t in body.get("similar_tickets") or []}
    assert prior["incident_id"] in ticket_ids
    assert current["incident_id"] not in ticket_ids
    kb_ids = {k["article_id"] for k in body.get("knowledge_articles") or []}
    assert article_id in kb_ids


def test_knowledge_suggest_accepts_q_tokens(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    kb = client.post(
        "/api/itsm/knowledge/articles",
        headers=auth_headers,
        json={
            "title": "Postgres connection pool exhaustion",
            "body": "Increase pool size when database connections spike.",
            "status": "draft",
            "category": "database",
            "tags": ["postgres", "pool"],
        },
    )
    assert kb.status_code == 201, kb.text
    article_id = kb.json()["article_id"]
    assert (
        client.post(
            f"/api/itsm/knowledge/articles/{article_id}/transition",
            headers=auth_headers,
            json={"status": "published"},
        ).status_code
        == 200
    )
    resp = client.get(
        "/api/itsm/knowledge/articles/suggest",
        headers=auth_headers,
        params={"q": "postgres pool exhaustion", "limit": 5},
    )
    assert resp.status_code == 200, resp.text
    ids = {row["article_id"] for row in resp.json().get("items") or []}
    assert article_id in ids


def test_similar_does_not_mutate_incident(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    doc = _create_incident(
        client,
        auth_headers,
        title="Minor label typo",
        description="Cosmetic UI issue",
        category="application",
    )
    iid = doc["incident_id"]
    before = client.get(f"/api/itsm/incidents/{iid}", headers=auth_headers).json()
    client.post(
        f"/api/itsm/incidents/{iid}/ai/similar",
        headers=auth_headers,
        json={"force_fallback": True},
    )
    after = client.get(f"/api/itsm/incidents/{iid}", headers=auth_headers).json()
    assert after["status"] == before["status"]
    assert after["updated_at"] == before["updated_at"]
    assert after.get("problem_id") == before.get("problem_id")


def test_ui_markers_and_version(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from app import __version__

    assert __version__ == "0.80.0"
    html = client.get("/", headers=auth_headers).text
    assert 'id="btnItsmIncSimilar"' in html
    assert 'id="itsmIncSimilarAssist"' in html
    assert __version__ in html
    api = client.get("/static/js/itsm/api.js", headers=auth_headers).text
    assert "/ai/similar" in api
    js = client.get("/static/js/itsm/incidents.js", headers=auth_headers).text
    assert "similarIncident" in js or "runSimilarAssist" in js
