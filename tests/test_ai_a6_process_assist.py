"""AI A6 — workflow / next-step process assist (no auto-advance)."""

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


def _mini_graph():
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start", "config": {}, "x": 0, "y": 0},
            {
                "id": "note",
                "type": "status_change",
                "label": "In progress",
                "config": {"status": "in_progress"},
                "x": 200,
                "y": 0,
            },
            {"id": "end", "type": "end", "label": "Done", "config": {}, "x": 400, "y": 0},
        ],
        "edges": [
            {"id": "e1", "from": "start", "to": "note"},
            {"id": "e2", "from": "note", "to": "end"},
        ],
    }


def test_incident_next_steps_legal_and_workflow(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    wf = client.post(
        "/api/itsm/workflows",
        headers=auth_headers,
        json={
            "name": "Incident triage flow",
            "description": "manual assist candidate",
            "applies_to": "incident",
            "trigger": "manual",
            "active": False,
            "graph": _mini_graph(),
        },
    )
    assert wf.status_code == 201, wf.text
    workflow_id = wf.json()["workflow_id"]
    pub = client.post(
        f"/api/itsm/workflows/{workflow_id}/publish",
        headers=auth_headers,
    )
    assert pub.status_code == 200, pub.text

    created = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "Portal login failures",
            "description": "Users cannot authenticate via SSO",
            "priority": "p2",
            "category": "access",
        },
    )
    assert created.status_code == 201, created.text
    iid = created.json()["incident_id"]
    assert created.json()["status"] == "new"

    resp = client.post(
        f"/api/itsm/incidents/{iid}/ai/next-steps",
        headers=auth_headers,
        json={"force_fallback": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "rule_based_fallback"
    assert set(body["legal_next_statuses"]) == {"in_progress", "on_hold", "cancelled"}
    assert body["safety"]["no_auto_transition"] is True
    assert body["safety"]["no_auto_advance"] is True
    assert body["safety"]["no_auto_approve"] is True
    wf_ids = {w["workflow_id"] for w in body.get("suggested_workflows") or []}
    assert workflow_id in wf_ids

    # Assist must not mutate ticket
    mid = client.get(f"/api/itsm/incidents/{iid}", headers=auth_headers).json()
    assert mid["status"] == "new"


def test_change_next_steps_and_problem_draft_on_resolved(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    chg = client.post(
        "/api/itsm/changes",
        headers=auth_headers,
        json={
            "title": "Routine patch window",
            "change_type": "standard",
            "priority": "p3",
        },
    )
    assert chg.status_code == 201, chg.text
    cid = chg.json()["change_id"]
    resp = client.post(
        f"/api/itsm/changes/{cid}/ai/next-steps",
        headers=auth_headers,
        json={"force_fallback": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "submitted" in body["legal_next_statuses"]
    assert body["problem_draft"] is None

    inc = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "Recurring VPN drop",
            "description": "Network VPN intermittent",
            "priority": "p3",
            "category": "network",
        },
    ).json()
    iid = inc["incident_id"]
    assert (
        client.post(
            f"/api/itsm/incidents/{iid}/transition",
            headers=auth_headers,
            json={"status": "in_progress"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/itsm/incidents/{iid}/transition",
            headers=auth_headers,
            json={"status": "resolved", "resolution_notes": "Temp fix"},
        ).status_code
        == 200
    )
    nxt = client.post(
        f"/api/itsm/incidents/{iid}/ai/next-steps",
        headers=auth_headers,
        json={"force_fallback": True},
    ).json()
    assert nxt["problem_draft"] is not None
    assert nxt["problem_draft"]["source_incident_id"] == iid
    # Still resolved — draft did not create a problem
    assert (
        client.get(f"/api/itsm/incidents/{iid}", headers=auth_headers).json()["status"]
        == "resolved"
    )


def test_ui_markers_and_version(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from app import __version__

    assert __version__ == "0.99.0"
    html = client.get("/", headers=auth_headers).text
    assert 'id="btnItsmIncNextSteps"' in html
    assert 'id="btnItsmChgNextSteps"' in html
    assert 'id="itsmIncAiStatus"' in html
    assert __version__ in html
    api = client.get("/static/js/itsm/api.js", headers=auth_headers).text
    assert "/ai/next-steps" in api
    assert "/api/ai/status" in api
