"""AI A3 — ITSM incident triage + summarization (assist only)."""

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
    client: TestClient, headers: dict[str, str], *, title: str, description: str
) -> dict:
    resp = client.post(
        "/api/itsm/incidents",
        headers=headers,
        json={
            "title": title,
            "description": description,
            "priority": "p3",
            "status": "new",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_triage_fallback_outage_keywords(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    doc = _create_incident(
        client,
        auth_headers,
        title="Production portal outage",
        description="Users cannot login; SSO auth failing across regions",
    )
    resp = client.post(
        f"/api/itsm/incidents/{doc['incident_id']}/ai/triage",
        headers=auth_headers,
        json={"force_fallback": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "rule_based_fallback"
    assert body["suggested_priority"] == "p1"
    # "portal" matches application before access keywords in the rule table
    assert body["suggested_category"] == "application"
    assert body["suggested_assignment_group"] == "application-support"
    assert body["safety"]["no_auto_transition"] is True
    assert body["safety"]["auto_apply"] is False
    assert body["apply_fields"]["priority"] == "p1"


def test_apply_triage_via_patch_not_silent(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    doc = _create_incident(
        client,
        auth_headers,
        title="Database latency on orders",
        description="Postgres queries slow; database CPU high",
    )
    iid = doc["incident_id"]
    triage = client.post(
        f"/api/itsm/incidents/{iid}/ai/triage",
        headers=auth_headers,
        json={"force_fallback": True},
    ).json()
    # Suggest alone must not mutate
    mid = client.get(f"/api/itsm/incidents/{iid}", headers=auth_headers).json()
    assert mid["priority"] == "p3"
    applied = client.patch(
        f"/api/itsm/incidents/{iid}",
        headers=auth_headers,
        json=triage["apply_fields"],
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["priority"] == triage["suggested_priority"]


def test_summarize_fallback_and_legal_transitions(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    doc = _create_incident(
        client,
        auth_headers,
        title="VPN intermittent",
        description="Network VPN drops for remote users",
    )
    iid = doc["incident_id"]
    client.post(
        f"/api/itsm/incidents/{iid}/transition",
        headers=auth_headers,
        json={"status": "in_progress", "comment": "Investigating"},
    )
    resp = client.post(
        f"/api/itsm/incidents/{iid}/ai/summarize",
        headers=auth_headers,
        json={"force_fallback": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["timeline_summary"]
    for st in body.get("suggested_next_statuses") or []:
        assert st in {"on_hold", "resolved", "cancelled"}
    assert body["safety"]["no_auto_transition"] is True
    # Ticket still in_progress — AI did not transition
    cur = client.get(f"/api/itsm/incidents/{iid}", headers=auth_headers).json()
    assert cur["status"] == "in_progress"


def test_update_succeeds_even_if_ai_would_fail(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    """Ticket mutations must not depend on AI availability."""
    doc = _create_incident(
        client,
        auth_headers,
        title="Minor UI glitch",
        description="Cosmetic label wrong",
    )
    iid = doc["incident_id"]
    # Even with AI path available as a side-call, PATCH must succeed independently.
    upd = client.patch(
        f"/api/itsm/incidents/{iid}",
        headers=auth_headers,
        json={"priority": "p4", "category": "application"},
    )
    assert upd.status_code == 200
    assert upd.json()["priority"] == "p4"


def test_ui_markers_and_version(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from app import __version__

    assert __version__ == "0.77.0"
    html = client.get("/", headers=auth_headers).text
    assert 'id="btnItsmIncTriage"' in html
    assert 'id="btnItsmIncSummarize"' in html
    assert __version__ in html
    js = client.get("/static/js/itsm/incidents.js", headers=auth_headers).text
    assert "triageIncident" in js or "/ai/triage" in js
    api = client.get("/static/js/itsm/api.js", headers=auth_headers).text
    assert "/ai/triage" in api
    assert "/ai/summarize" in api
