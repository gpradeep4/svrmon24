"""ITSM SLA policies + tracking — functional coverage for 0.42.0."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import __version__
from app.db import get_itsm_database
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_sla_slice() -> None:
    assert __version__ == "0.58.0"


def _policy_payload(**overrides):
    body = {
        "name": "Incident default SLA",
        "description": "Response + resolution by priority",
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
                    {"priority": "p2", "minutes": 240},
                    {"priority": "p3", "minutes": 480},
                    {"priority": "p4", "minutes": 1440},
                ],
            },
        ],
        "calendar": {"timezone": "UTC", "business_hours_only": False},
    }
    body.update(overrides)
    return body


def test_sla_policy_crud_and_auto_attach(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post(
        "/api/itsm/sla/policies",
        headers=auth_headers,
        json=_policy_payload(),
    )
    assert created.status_code == 201, created.text
    policy = created.json()
    assert policy["policy_id"].startswith("SLA-")
    assert policy["active"] is True
    assert policy["applies_to"] == "incident"
    assert len(policy["targets"]) == 2
    policy_id = policy["policy_id"]

    listed = client.get(
        "/api/itsm/sla/policies?applies_to=incident&active=true",
        headers=auth_headers,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] >= 1

    patched = client.patch(
        f"/api/itsm/sla/policies/{policy_id}",
        headers=auth_headers,
        json={"description": "Updated desc"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["description"] == "Updated desc"

    incident = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "SLA tracked outage",
            "description": "Clock should attach",
            "priority": "p2",
        },
    )
    assert incident.status_code == 201, incident.text
    incident_id = incident.json()["incident_id"]
    assert "sla_tracking_ids" in incident.json()
    assert len(incident.json()["sla_tracking_ids"]) >= 1

    tracking = client.get(
        f"/api/itsm/sla/tracking?ticket_type=incident&ticket_id={incident_id}",
        headers=auth_headers,
    )
    assert tracking.status_code == 200, tracking.text
    rows = tracking.json()["items"]
    assert len(rows) >= 2
    metrics = {r["metric"] for r in rows}
    assert "response" in metrics
    assert "resolution" in metrics
    assert all(r["status"] == "running" for r in rows)
    assert all(r["policy_id"] == policy_id for r in rows)
    assert all(r["priority_at_start"] == "p2" for r in rows)

    summary = client.get(
        f"/api/itsm/sla/summary/incident/{incident_id}",
        headers=auth_headers,
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["worst_status"] == "running"
    assert summary.json()["counts"]["running"] >= 2

    # Priority change cancels open clocks and re-attaches with new targets.
    updated = client.patch(
        f"/api/itsm/incidents/{incident_id}",
        headers=auth_headers,
        json={"priority": "p1"},
    )
    assert updated.status_code == 200, updated.text
    after = client.get(
        f"/api/itsm/sla/tracking?ticket_type=incident&ticket_id={incident_id}",
        headers=auth_headers,
    )
    assert after.status_code == 200
    statuses = {r["status"] for r in after.json()["items"]}
    assert "cancelled" in statuses
    running = [r for r in after.json()["items"] if r["status"] == "running"]
    assert running
    assert all(r["priority_at_start"] == "p1" for r in running)

    itsm = get_itsm_database()
    assert itsm is not None
    assert itsm["itsm_sla_policies"].count_documents({}) >= 1
    assert itsm["itsm_sla_tracking"].count_documents({}) >= 1


def test_sla_pause_on_hold_and_resolution_met(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    pol = client.post(
        "/api/itsm/sla/policies",
        headers=auth_headers,
        json=_policy_payload(name="Pause/resolve SLA"),
    )
    assert pol.status_code == 201, pol.text

    incident = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={"title": "Hold then resolve", "priority": "p3"},
    )
    assert incident.status_code == 201, incident.text
    incident_id = incident.json()["incident_id"]

    # Leave new → in_progress: response should complete (met).
    t1 = client.post(
        f"/api/itsm/incidents/{incident_id}/transition",
        headers=auth_headers,
        json={"status": "in_progress"},
    )
    assert t1.status_code == 200, t1.text

    tracking = client.get(
        f"/api/itsm/sla/tracking?ticket_id={incident_id}",
        headers=auth_headers,
    )
    assert tracking.status_code == 200
    by_metric = {r["metric"]: r for r in tracking.json()["items"] if r["status"] != "cancelled"}
    assert by_metric["response"]["status"] == "met"
    assert by_metric["resolution"]["status"] == "running"

    # Pause on on_hold.
    t2 = client.post(
        f"/api/itsm/incidents/{incident_id}/transition",
        headers=auth_headers,
        json={"status": "on_hold"},
    )
    assert t2.status_code == 200, t2.text
    paused = client.get(
        f"/api/itsm/sla/tracking?ticket_id={incident_id}&status=paused",
        headers=auth_headers,
    )
    assert paused.status_code == 200
    assert paused.json()["total"] >= 1

    # Resume then resolve → resolution met.
    t3 = client.post(
        f"/api/itsm/incidents/{incident_id}/transition",
        headers=auth_headers,
        json={"status": "in_progress"},
    )
    assert t3.status_code == 200, t3.text
    t4 = client.post(
        f"/api/itsm/incidents/{incident_id}/transition",
        headers=auth_headers,
        json={"status": "resolved", "resolution_notes": "Fixed"},
    )
    assert t4.status_code == 200, t4.text

    final = client.get(
        f"/api/itsm/sla/tracking?ticket_id={incident_id}",
        headers=auth_headers,
    )
    assert final.status_code == 200
    resolution_rows = [
        r for r in final.json()["items"] if r["metric"] == "resolution" and r["status"] != "cancelled"
    ]
    assert resolution_rows
    assert resolution_rows[0]["status"] == "met"

    activities = client.get(
        f"/api/itsm/incident/{incident_id}/activities",
        headers=auth_headers,
    )
    assert activities.status_code == 200
    types = {a["activity_type"] for a in activities.json()["items"]}
    assert "sla" in types


def test_sla_overdue_filter_marks_breach(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    pol = client.post(
        "/api/itsm/sla/policies",
        headers=auth_headers,
        json=_policy_payload(
            name="Tight SLA",
            targets=[
                {
                    "metric": "resolution",
                    "priority_targets": [{"priority": "p1", "minutes": 60}],
                }
            ],
        ),
    )
    assert pol.status_code == 201, pol.text

    incident = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={"title": "Already late", "priority": "p1"},
    )
    assert incident.status_code == 201, incident.text
    incident_id = incident.json()["incident_id"]

    itsm = get_itsm_database()
    assert itsm is not None
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    itsm["itsm_sla_tracking"].update_many(
        {"ticket_id": incident_id, "status": "running"},
        {"$set": {"due_at": past}},
    )

    overdue = client.get(
        f"/api/itsm/sla/tracking?ticket_id={incident_id}&overdue=true",
        headers=auth_headers,
    )
    assert overdue.status_code == 200, overdue.text
    assert overdue.json()["total"] >= 1
    assert all(r["status"] == "breached" for r in overdue.json()["items"])

    dash = client.get("/api/itsm/dashboard/summary", headers=auth_headers)
    assert dash.status_code == 200
    assert dash.json()["sla_breaches"] >= 1


def test_sla_multi_dimensional_most_specific_wins(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    """Tier1+VIP policy beats a generic wildcard policy for the same ticket type."""
    generic = client.post(
        "/api/itsm/sla/policies",
        headers=auth_headers,
        json=_policy_payload(name="Generic incident SLA", priority_order=100),
    )
    assert generic.status_code == 201, generic.text
    assert generic.json().get("match") in ({}, None) or generic.json()["match"] == {}

    tier = client.post(
        "/api/itsm/sla/policies",
        headers=auth_headers,
        json=_policy_payload(
            name="Tier1 VIP SLA",
            priority_order=10,
            match={
                "service_tier": "tier1",
                "customer_class": "vip",
                "category": "network",
            },
            targets=[
                {
                    "metric": "response",
                    "priority_targets": [
                        {"priority": "p1", "minutes": 5},
                        {"priority": "p2", "minutes": 10},
                    ],
                },
                {
                    "metric": "resolution",
                    "priority_targets": [
                        {"priority": "p1", "minutes": 30},
                        {"priority": "p2", "minutes": 60},
                    ],
                },
            ],
        ),
    )
    assert tier.status_code == 201, tier.text
    tier_id = tier.json()["policy_id"]
    assert tier.json()["match"]["service_tier"] == "tier1"
    assert tier.json()["priority_order"] == 10

    # Non-matching ticket → generic (wildcard) wins.
    plain = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={"title": "Plain outage", "priority": "p2"},
    )
    assert plain.status_code == 201, plain.text
    plain_trk = client.get(
        f"/api/itsm/sla/tracking?ticket_id={plain.json()['incident_id']}",
        headers=auth_headers,
    )
    assert plain_trk.status_code == 200
    plain_policies = {r["policy_id"] for r in plain_trk.json()["items"]}
    assert generic.json()["policy_id"] in plain_policies
    assert tier_id not in plain_policies

    # Matching Tier1+VIP+network → specific policy wins; score > 0; matched_fields set.
    vip = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "VIP VPN outage",
            "priority": "p2",
            "service_tier": "tier1",
            "customer_class": "vip",
            "category": "network",
            "subcategory": "vpn",
            "ci_criticality": "critical",
        },
    )
    assert vip.status_code == 201, vip.text
    vip_id = vip.json()["incident_id"]
    vip_trk = client.get(
        f"/api/itsm/sla/tracking?ticket_id={vip_id}",
        headers=auth_headers,
    )
    assert vip_trk.status_code == 200, vip_trk.text
    rows = [r for r in vip_trk.json()["items"] if r["status"] == "running"]
    assert rows
    assert all(r["policy_id"] == tier_id for r in rows)
    assert rows[0]["match_score"] >= 100 + 80 + 60  # tier + vip + category
    assert rows[0]["matched_fields"]["service_tier"] == "tier1"
    assert rows[0]["matched_fields"]["customer_class"] == "vip"
    assert "tier1" in (rows[0].get("match_reason") or "")
    # Tighter response target from Tier1 policy (10m for p2).
    resp = next(r for r in rows if r["metric"] == "response")
    assert resp["target_minutes"] == 10

    # Context change to non-tier reselects generic.
    patched = client.patch(
        f"/api/itsm/incidents/{vip_id}",
        headers=auth_headers,
        json={"service_tier": "tier3", "customer_class": "standard"},
    )
    assert patched.status_code == 200, patched.text
    after = client.get(
        f"/api/itsm/sla/tracking?ticket_id={vip_id}&status=running",
        headers=auth_headers,
    )
    assert after.status_code == 200
    running = after.json()["items"]
    assert running
    assert all(r["policy_id"] == generic.json()["policy_id"] for r in running)


def test_sla_match_priorities_and_ci_snapshot(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    pol = client.post(
        "/api/itsm/sla/policies",
        headers=auth_headers,
        json=_policy_payload(
            name="P1 critical CI only",
            match={
                "priorities": ["p1"],
                "ci_criticality": "critical",
            },
            targets=[
                {
                    "metric": "resolution",
                    "priority_targets": [{"priority": "p1", "minutes": 45}],
                }
            ],
        ),
    )
    assert pol.status_code == 201, pol.text

    # p2 should not match this policy (and no generic) → no tracking.
    miss = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "p2 with critical CI",
            "priority": "p2",
            "ci_criticality": "critical",
        },
    )
    assert miss.status_code == 201
    miss_trk = client.get(
        f"/api/itsm/sla/tracking?ticket_id={miss.json()['incident_id']}",
        headers=auth_headers,
    )
    assert miss_trk.json()["total"] == 0

    hit = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "p1 critical",
            "priority": "p1",
            "ci_criticality": "critical",
        },
    )
    assert hit.status_code == 201
    hit_trk = client.get(
        f"/api/itsm/sla/tracking?ticket_id={hit.json()['incident_id']}",
        headers=auth_headers,
    )
    assert hit_trk.json()["total"] >= 1
    row = hit_trk.json()["items"][0]
    assert row["policy_id"] == pol.json()["policy_id"]
    assert "ci_criticality" in row["matched_fields"]
    assert row["matched_fields"]["priority"] == "p1"


def test_sla_frontend_shell_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.58.0"' in html
    assert 'data-tab="itsm-sla"' in html
    assert 'id="tab-itsm-sla"' in html
    assert "itsm/sla.js?v=0.58.0" in html
    assert 'id="itsmSlaModal"' in html
    assert 'id="itsmIncSlaBadges"' in html
    assert 'id="itsmSlaMatchTier"' in html
    assert "Match conditions" in html
