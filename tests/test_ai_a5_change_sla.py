"""AI A5 — ITSM change risk text + SLA at-risk assist."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def _policy_payload(**overrides):
    body = {
        "name": "Incident short SLA",
        "description": "Tight clocks for at-risk tests",
        "active": True,
        "applies_to": "incident",
        "priority_order": 100,
        "match": {},
        "pause_on_statuses": ["on_hold"],
        "targets": [
            {
                "metric": "response",
                "priority_targets": [
                    {"priority": "p1", "minutes": 15},
                    {"priority": "p2", "minutes": 30},
                    {"priority": "p3", "minutes": 60},
                    {"priority": "p4", "minutes": 240},
                ],
            },
            {
                "metric": "resolution",
                "priority_targets": [
                    {"priority": "p1", "minutes": 60},
                    {"priority": "p2", "minutes": 120},
                    {"priority": "p3", "minutes": 180},
                    {"priority": "p4", "minutes": 480},
                ],
            },
        ],
        "calendar": {"timezone": "UTC", "business_hours_only": False},
    }
    body.update(overrides)
    return body


def test_change_risk_fallback_emergency(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    created = client.post(
        "/api/itsm/changes",
        headers=auth_headers,
        json={
            "title": "Emergency firewall rule push",
            "description": "Urgent network change",
            "change_type": "emergency",
            "priority": "p1",
            "risk": "high",
            "cab_required": True,
            "backout_plan": "Revert ACL snapshot",
        },
    )
    assert created.status_code == 201, created.text
    cid = created.json()["change_id"]
    resp = client.post(
        f"/api/itsm/changes/{cid}/ai/risk",
        headers=auth_headers,
        json={"force_fallback": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "rule_based_fallback"
    assert body["risk_band"] in {"medium", "high"}
    assert body["safety"]["no_auto_cab"] is True
    assert body["safety"]["no_auto_approve"] is True
    assert "checklist" in body and body["checklist"]
    # Suggest alone must not mutate change
    mid = client.get(f"/api/itsm/changes/{cid}", headers=auth_headers).json()
    assert mid["status"] == created.json()["status"]
    assert mid.get("risk") == "high"


def test_sla_at_risk_deterministic_under_20pct(
    providers_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    pol = client.post(
        "/api/itsm/sla/policies",
        headers=auth_headers,
        json=_policy_payload(),
    )
    assert pol.status_code == 201, pol.text

    incident = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "Near-breach ticket",
            "description": "Clock almost expired",
            "priority": "p3",
        },
    )
    assert incident.status_code == 201, incident.text
    iid = incident.json()["incident_id"]

    tracking = client.get(
        f"/api/itsm/sla/tracking?ticket_type=incident&ticket_id={iid}",
        headers=auth_headers,
    )
    assert tracking.status_code == 200, tracking.text
    rows = tracking.json()["items"]
    assert rows, "expected auto-attached SLA rows"

    # Force remaining time under 20% by backdating started_at / due_at
    from app.db import require_itsm_database
    from app.itsm.services.indexes import SLA_TRACKING

    now = datetime.now(timezone.utc)
    coll = require_itsm_database()[SLA_TRACKING]
    for row in rows:
        coll.update_one(
            {"tracking_id": row["tracking_id"]},
            {
                "$set": {
                    "started_at": now - timedelta(minutes=50),
                    "due_at": now + timedelta(minutes=5),
                    "target_minutes": 55,
                    "status": "running",
                }
            },
        )

    before = client.get(
        f"/api/itsm/sla/tracking?ticket_type=incident&ticket_id={iid}",
        headers=auth_headers,
    ).json()["items"]
    before_due = {r["tracking_id"]: r["due_at"] for r in before}

    resp = client.post(
        "/api/itsm/sla/ai/at-risk",
        headers=auth_headers,
        json={
            "ticket_type": "incident",
            "ticket_id": iid,
            "force_fallback": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "rule_based_fallback"
    assert body["at_risk"] is True
    assert body["safety"]["no_clock_mutation"] is True
    assert any(item.get("at_risk") for item in body.get("items") or [])

    after = client.get(
        f"/api/itsm/sla/tracking?ticket_type=incident&ticket_id={iid}",
        headers=auth_headers,
    ).json()["items"]
    after_due = {r["tracking_id"]: r["due_at"] for r in after}
    assert after_due == before_due


def test_ui_markers_and_version(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    from app import __version__

    assert __version__ == "0.79.0"
    html = client.get("/", headers=auth_headers).text
    assert 'id="btnItsmChgRisk"' in html
    assert 'id="btnItsmIncSlaRisk"' in html
    assert __version__ in html
    api = client.get("/static/js/itsm/api.js", headers=auth_headers).text
    assert "/ai/risk" in api
    assert "/sla/ai/at-risk" in api
