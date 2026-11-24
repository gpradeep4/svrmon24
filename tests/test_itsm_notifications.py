"""ITSM in-app Notification Management — functional coverage for 0.42.0."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import __version__
from app.db import get_itsm_database
from app.itsm.services import notifications as notifications_service
from app.itsm.services import sla as sla_service
from app.permissions import (
    ALL_PERMISSIONS,
    PERM_ITSM_NOTIFICATION_READ,
    permissions_for_role,
)
from app.tenancy import MEMBERSHIP_ROLE_VIEWER
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_notifications_slice() -> None:
    assert __version__ == "0.97.0"


def test_notification_permissions_in_catalog() -> None:
    assert PERM_ITSM_NOTIFICATION_READ in ALL_PERMISSIONS
    viewer = permissions_for_role(MEMBERSHIP_ROLE_VIEWER)
    assert PERM_ITSM_NOTIFICATION_READ in viewer


def _create_incident(client: TestClient, auth_headers: dict[str, str], **overrides):
    body = {
        "title": "VPN edge down",
        "description": "Users cannot connect",
        "priority": "p2",
        "category": "network",
    }
    body.update(overrides)
    resp = client.post("/api/itsm/incidents", headers=auth_headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_assignment_and_status_hooks_and_inbox_actions(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    incident = _create_incident(client, auth_headers)
    incident_id = incident["incident_id"]
    tid = incident["tenant_id"]
    itsm = get_itsm_database()

    # Assign to another user — actor (testuser) is excluded from recipients.
    assigned = client.patch(
        f"/api/itsm/incidents/{incident_id}",
        headers=auth_headers,
        json={"assignee_user_id": "ops.alice"},
    )
    assert assigned.status_code == 200, assigned.text
    assert (
        itsm["itsm_notifications"].count_documents(
            {
                "event_type": "assignment",
                "ticket_id": incident_id,
                "recipient_user_id": "ops.alice",
                "channel": "in_app",
            }
        )
        == 1
    )

    transitioned = client.post(
        f"/api/itsm/incidents/{incident_id}/transition",
        headers=auth_headers,
        json={"status": "in_progress", "comment": "Investigating"},
    )
    assert transitioned.status_code == 200, transitioned.text
    assert (
        itsm["itsm_notifications"].count_documents(
            {
                "event_type": "status_change",
                "ticket_id": incident_id,
                "recipient_user_id": "ops.alice",
            }
        )
        == 1
    )

    # Seed an inbox row for the authenticated Basic user to exercise APIs.
    seeded = notifications_service.emit(
        tenant_id=tid,
        event_type="assignment",
        recipient_user_ids=["testuser"],
        subject=f"Assigned: {incident.get('number_display') or incident_id}",
        body=f"You were assigned to incident {incident_id}.",
        ticket_type="incident",
        ticket_id=incident_id,
        actor={"username": "manager", "user_id": "manager"},
    )
    assert seeded
    notification_id = seeded[0]["notification_id"]

    inbox = client.get("/api/itsm/notifications", headers=auth_headers)
    assert inbox.status_code == 200, inbox.text
    payload = inbox.json()
    assert payload["total"] >= 1
    assert payload["unread_count"] >= 1
    assert any(row["notification_id"] == notification_id for row in payload["items"])
    assert all(row["recipient_user_id"] == "testuser" for row in payload["items"])

    unread = client.get("/api/itsm/notifications/unread-count", headers=auth_headers)
    assert unread.status_code == 200, unread.text
    assert unread.json()["unread_count"] >= 1

    marked = client.post(
        f"/api/itsm/notifications/{notification_id}/read",
        headers=auth_headers,
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["status"] == "read"
    assert marked.json()["read_at"] is not None

    unread_mark = client.post(
        f"/api/itsm/notifications/{notification_id}/unread",
        headers=auth_headers,
    )
    assert unread_mark.status_code == 200, unread_mark.text
    assert unread_mark.json()["status"] == "unread"

    archived = client.post(
        f"/api/itsm/notifications/{notification_id}/archive",
        headers=auth_headers,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"

    default_list = client.get("/api/itsm/notifications", headers=auth_headers)
    assert default_list.status_code == 200
    assert all(
        row["notification_id"] != notification_id
        for row in default_list.json()["items"]
    )

    with_archived = client.get(
        "/api/itsm/notifications?include_archived=true&status=archived",
        headers=auth_headers,
    )
    assert with_archived.status_code == 200
    assert any(
        row["notification_id"] == notification_id
        for row in with_archived.json()["items"]
    )


def test_approval_requested_and_decided_hooks(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    incident = _create_incident(client, auth_headers)
    incident_id = incident["incident_id"]
    itsm = get_itsm_database()

    client.patch(
        f"/api/itsm/incidents/{incident_id}",
        headers=auth_headers,
        json={"assignee_user_id": "ops.alice"},
    )

    created = client.post(
        "/api/itsm/approvals",
        headers=auth_headers,
        json={
            "title": "Emergency change window",
            "ticket_type": "incident",
            "ticket_id": incident_id,
            "approver_user_ids": ["testuser", "cab.lead"],
        },
    )
    assert created.status_code == 201, created.text
    approval_id = created.json()["approval_id"]

    # Actor excluded → testuser filtered; cab.lead still notified.
    assert (
        itsm["itsm_notifications"].count_documents(
            {
                "event_type": "approval_requested",
                "approval_id": approval_id,
                "recipient_user_id": "cab.lead",
            }
        )
        == 1
    )

    decided = client.post(
        f"/api/itsm/approvals/{approval_id}/decide",
        headers=auth_headers,
        json={"decision": "approved", "comment": "OK"},
    )
    assert decided.status_code == 200, decided.text

    # Decide notifies created_by + assignee, excluding actor (testuser).
    # Assignee ops.alice should receive approval_decided.
    assert (
        itsm["itsm_notifications"].count_documents(
            {
                "event_type": "approval_decided",
                "approval_id": approval_id,
                "recipient_user_id": "ops.alice",
            }
        )
        == 1
    )

    # Seed decide row into testuser inbox for click-through fields.
    rows = notifications_service.emit(
        tenant_id=incident["tenant_id"],
        event_type="approval_decided",
        recipient_user_ids=["testuser"],
        subject="Approval approved: Emergency change window",
        body=f"Approval {approval_id} was approved",
        ticket_type="incident",
        ticket_id=incident_id,
        approval_id=approval_id,
        actor={"username": "cab.lead", "user_id": "cab.lead"},
    )
    assert rows
    inbox = client.get(
        "/api/itsm/notifications?event_type=approval_decided",
        headers=auth_headers,
    )
    assert inbox.status_code == 200
    assert any(row["approval_id"] == approval_id for row in inbox.json()["items"])


def test_sla_breach_notification_best_effort(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    incident = _create_incident(client, auth_headers, priority="p1")
    incident_id = incident["incident_id"]
    tid = incident["tenant_id"]
    itsm = get_itsm_database()

    client.patch(
        f"/api/itsm/incidents/{incident_id}",
        headers=auth_headers,
        json={"assignee_user_id": "testuser"},
    )

    past = datetime.now(timezone.utc) - timedelta(hours=2)
    tracking_id = "SLA-TESTBREACH01"
    itsm["itsm_sla_tracking"].insert_one(
        {
            "tenant_id": tid,
            "tracking_id": tracking_id,
            "policy_id": "SLA-POL-TEST",
            "ticket_type": "incident",
            "ticket_id": incident_id,
            "metric": "response",
            "status": "running",
            "due_at": past,
            "started_at": past - timedelta(hours=1),
            "created_at": past,
            "updated_at": past,
        }
    )

    refreshed = sla_service._refresh_breach_doc(
        itsm["itsm_sla_tracking"].find_one({"tracking_id": tracking_id})
    )
    assert refreshed.get("status") == "breached"

    inbox = client.get(
        "/api/itsm/notifications?event_type=sla_breach",
        headers=auth_headers,
    )
    assert inbox.status_code == 200, inbox.text
    assert inbox.json()["total"] >= 1
    assert any(
        row["ticket_id"] == incident_id and row["tracking_id"] == tracking_id
        for row in inbox.json()["items"]
    )


def test_notification_tenant_isolation(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    incident = _create_incident(client, auth_headers)
    tid = incident["tenant_id"]
    seeded = notifications_service.emit(
        tenant_id=tid,
        event_type="assignment",
        recipient_user_ids=["testuser"],
        subject="Tenant scoped notice",
        body="Isolation check",
        ticket_type="incident",
        ticket_id=incident["incident_id"],
        actor={"username": "manager", "user_id": "manager"},
    )
    assert seeded
    own_id = seeded[0]["notification_id"]

    foreign = dict(
        get_itsm_database()["itsm_notifications"].find_one(
            {"notification_id": own_id}
        )
    )
    foreign.pop("_id", None)
    foreign["tenant_id"] = "tenant-other-org"
    foreign["notification_id"] = "NTF-FOREIGN01"
    get_itsm_database()["itsm_notifications"].insert_one(foreign)

    missing = client.get(
        "/api/itsm/notifications/NTF-FOREIGN01", headers=auth_headers
    )
    assert missing.status_code == 404

    own = client.get(f"/api/itsm/notifications/{own_id}", headers=auth_headers)
    assert own.status_code == 200
    assert own.json()["tenant_id"] == tid


def test_frontend_notification_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.97.0"' in html
    assert 'data-tab="itsm-notifications"' in html
    assert 'id="tab-itsm-notifications"' in html
    assert "itsm/notifications.js?v=0.97.0" in html
    assert 'id="itsmNotifNavBadge"' in html
    assert 'id="itsmNotifBody"' in html
