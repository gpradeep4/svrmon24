"""ITSM Dashboard & Reports analytics — functional coverage for 0.42.0."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import __version__
from app.db import get_itsm_database
from app.itsm.services import notifications as notifications_service
from app.permissions import PERM_ITSM_DASHBOARD_READ, permissions_for_role
from app.tenancy import MEMBERSHIP_ROLE_VIEWER
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_dashboard_slice() -> None:
    assert __version__ == "0.99.14"


def test_dashboard_permission_for_viewer() -> None:
    viewer = permissions_for_role(MEMBERSHIP_ROLE_VIEWER)
    assert PERM_ITSM_DASHBOARD_READ in viewer


def _create_incident(client: TestClient, auth_headers: dict[str, str], **overrides):
    body = {
        "title": "Edge VPN flap",
        "description": "Intermittent disconnects",
        "priority": "p1",
        "category": "network",
    }
    body.update(overrides)
    resp = client.post("/api/itsm/incidents", headers=auth_headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_change(client: TestClient, auth_headers: dict[str, str], **overrides):
    body = {
        "title": "Firewall rule update",
        "description": "Open 443 for partner",
        "change_type": "normal",
        "priority": "p2",
        "risk": "low",
    }
    body.update(overrides)
    resp = client.post("/api/itsm/changes", headers=auth_headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_problem(client: TestClient, auth_headers: dict[str, str], **overrides):
    body = {
        "title": "Recurring VPN flaps",
        "description": "Root cause unknown",
        "priority": "p2",
    }
    body.update(overrides)
    resp = client.post("/api/itsm/problems", headers=auth_headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_dashboard_summary_aggregates_and_window(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    inc = _create_incident(client, auth_headers)
    chg = _create_change(client, auth_headers)
    prb = _create_problem(client, auth_headers)
    tid = inc["tenant_id"]
    itsm = get_itsm_database()

    approval = client.post(
        "/api/itsm/approvals",
        headers=auth_headers,
        json={
            "title": "CAB for firewall change",
            "ticket_type": "change",
            "ticket_id": chg["change_id"],
            "approver_user_ids": ["cab.lead"],
        },
    )
    assert approval.status_code == 201, approval.text

    article = client.post(
        "/api/itsm/knowledge/articles",
        headers=auth_headers,
        json={
            "title": "VPN flap runbook",
            "body": "Collect logs, bounce gateway.",
            "status": "draft",
            "category": "network",
            "tags": ["vpn"],
        },
    )
    assert article.status_code == 201, article.text
    published = client.post(
        f"/api/itsm/knowledge/articles/{article.json()['article_id']}/transition",
        headers=auth_headers,
        json={"status": "published"},
    )
    assert published.status_code == 200, published.text

    notifications_service.emit(
        tenant_id=tid,
        event_type="assignment",
        recipient_user_ids=["ops.alice"],
        subject="Assigned: test",
        body="You were assigned.",
        ticket_type="incident",
        ticket_id=inc["incident_id"],
        actor={"username": "manager", "user_id": "manager"},
    )

    now = datetime.now(timezone.utc)
    itsm["itsm_sla_tracking"].insert_one(
        {
            "tenant_id": tid,
            "tracking_id": "SLA-TRK-BREACH1",
            "policy_id": "SLA-POL-DEMO",
            "ticket_type": "incident",
            "ticket_id": inc["incident_id"],
            "metric": "resolution",
            "status": "breached",
            "due_at": now - timedelta(hours=2),
            "breached_at": now - timedelta(hours=1),
            "created_at": now - timedelta(days=1),
            "updated_at": now,
        }
    )
    itsm["itsm_sla_tracking"].insert_one(
        {
            "tenant_id": tid,
            "tracking_id": "SLA-TRK-RISK1",
            "policy_id": "SLA-POL-DEMO",
            "ticket_type": "incident",
            "ticket_id": inc["incident_id"],
            "metric": "response",
            "status": "running",
            "due_at": now + timedelta(hours=6),
            "breached_at": None,
            "created_at": now - timedelta(hours=1),
            "updated_at": now,
        }
    )
    itsm["itsm_workflow_executions"].insert_one(
        {
            "tenant_id": tid,
            "execution_id": "WFX-DASH01",
            "workflow_id": "WF-DASH01",
            "workflow_version": 1,
            "ticket_type": "change",
            "ticket_id": chg["change_id"],
            "status": "waiting_approval",
            "current_node_id": "approve",
            "context": {},
            "history": [],
            "created_at": now,
            "updated_at": now,
        }
    )

    # Foreign-tenant noise must not appear in aggregates.
    itsm["itsm_incidents"].insert_one(
        {
            "tenant_id": "tenant-other-org",
            "incident_id": "INC-FOREIGN-DASH",
            "number": 999888,
            "number_display": "INC-999888",
            "title": "Other tenant",
            "status": "new",
            "priority": "p1",
            "created_at": now,
            "updated_at": now,
        }
    )

    summary = client.get("/api/itsm/dashboard/summary", headers=auth_headers)
    assert summary.status_code == 200, summary.text
    payload = summary.json()
    assert payload["tenant_id"] == tid
    assert payload["open_incidents"] >= 1
    assert payload["open_changes"] >= 1
    assert payload["open_problems"] >= 1
    assert payload["open_by_priority"].get("p1", 0) >= 1
    assert payload["incidents_by_status"].get("new", 0) >= 1
    assert payload["changes_by_status"]
    assert payload["problems_by_status"]
    assert payload["pending_approvals"] >= 1
    assert payload["sla_breaches"] >= 1
    assert payload["sla_at_risk"] >= 1
    assert payload["workflows_in_progress"] >= 1
    assert payload["knowledge_published"] >= 1
    assert payload["notifications_unread"] >= 1
    assert payload["window_days"] is None

    windowed = client.get(
        "/api/itsm/dashboard/summary?window_days=7",
        headers=auth_headers,
    )
    assert windowed.status_code == 200, windowed.text
    win = windowed.json()
    assert win["window_days"] == 7
    assert win["window_start"]
    assert win["created_in_window"]["incidents"] >= 1
    assert win["created_in_window"]["changes"] >= 1
    assert win["created_in_window"]["problems"] >= 1

    bad = client.get(
        "/api/itsm/dashboard/summary?window_days=14",
        headers=auth_headers,
    )
    assert bad.status_code == 400

    # Ensure foreign open incident was not counted into this tenant's open P1.
    assert payload["open_incidents"] == itsm["itsm_incidents"].count_documents(
        {
            "tenant_id": tid,
            "status": {"$in": ["new", "in_progress", "on_hold"]},
        }
    )

    # Keep references used so linters don't complain if helpers expand later.
    assert prb["problem_id"]
    assert chg["change_id"]


def test_dashboard_reports_series(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _create_incident(client, auth_headers, title="Series A")
    _create_incident(client, auth_headers, title="Series B", priority="p2")

    reports = client.get(
        "/api/itsm/dashboard/reports?window_days=30",
        headers=auth_headers,
    )
    assert reports.status_code == 200, reports.text
    payload = reports.json()
    assert payload["window_days"] == 30
    assert payload["open_incidents"] >= 2
    assert isinstance(payload["series_daily_created"], list)
    assert len(payload["series_daily_created"]) >= 30
    assert sum(row["incidents"] for row in payload["series_daily_created"]) >= 2
    assert payload["created_in_window"]["incidents"] >= 2


def test_dashboard_requires_auth(client: TestClient, clean_db) -> None:
    assert client.get("/api/itsm/dashboard/summary").status_code in (401, 403)
    assert client.get("/api/itsm/dashboard/reports").status_code in (401, 403)


def test_frontend_dashboard_reports_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.14"' in html
    assert 'data-tab="itsm-dashboard"' in html
    assert 'data-tab="itsm-reports"' in html
    assert 'id="itsmDashIncStatusChart"' in html
    assert 'id="itsmRepVolumeChart"' in html
    assert "/static/js/itsm/dashboard.js" in html
    assert "/static/js/itsm/reports.js" in html
