"""ITSM N8 production hardening pack — groups, attachments, SLA clock, watchers, related."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO

from app import __version__
from app.itsm.services.sla_clock import (
    add_business_minutes,
    business_seconds_between,
    compute_due_at,
)
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_hardening_slice() -> None:
    assert __version__ == "0.79.0"


def test_frontend_exposes_groups_and_hardening_hooks() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'data-tab="itsm-groups"' in html
    assert "itsm/groups.js" in html
    assert 'id="itsmGroupPickerList"' in html
    assert 'id="itsmFieldAssignmentGroup"' in html
    assert 'id="itsmIncAttachList"' in html
    assert 'id="itsmSlaCalHolidays"' in html


def test_assignment_groups_crud_and_picker(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post(
        "/api/itsm/assignment-groups",
        headers=auth_headers,
        json={
            "name": "NOC",
            "description": "Network ops",
            "email": "noc@example.com",
            "member_user_ids": ["user-a", "user-b"],
            "active": True,
        },
    )
    assert created.status_code == 201, created.text
    group = created.json()
    assert group["group_id"].startswith("AG-")
    assert group["name"] == "NOC"
    assert group["name_lower"] == "noc"

    clash = client.post(
        "/api/itsm/assignment-groups",
        headers=auth_headers,
        json={"name": "noc", "active": True},
    )
    assert clash.status_code == 409

    listed = client.get("/api/itsm/assignment-groups", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    picker = client.get("/api/itsm/assignment-groups/picker", headers=auth_headers)
    assert picker.status_code == 200
    assert "NOC" in picker.json()["items"]

    patched = client.patch(
        f"/api/itsm/assignment-groups/{group['group_id']}",
        headers=auth_headers,
        json={"description": "Updated"},
    )
    assert patched.status_code == 200
    assert patched.json()["description"] == "Updated"


def test_ticket_attachments_limits_and_tenant_scope(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    inc = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={"title": "Attach me", "priority": "p3"},
    )
    assert inc.status_code == 201, inc.text
    incident_id = inc.json()["incident_id"]

    ok = client.post(
        f"/api/itsm/incident/{incident_id}/attachments",
        headers=auth_headers,
        files={"file": ("note.txt", BytesIO(b"hello evidence"), "text/plain")},
    )
    assert ok.status_code == 201, ok.text
    att = ok.json()
    assert att["attachment_id"].startswith("ATT-")
    assert att["filename"] == "note.txt"
    assert att["size_bytes"] == len(b"hello evidence")
    assert "content" not in att

    listed = client.get(
        f"/api/itsm/incident/{incident_id}/attachments", headers=auth_headers
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    downloaded = client.get(
        f"/api/itsm/attachments/{att['attachment_id']}/content",
        headers=auth_headers,
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"hello evidence"

    bad_type = client.post(
        f"/api/itsm/incident/{incident_id}/attachments",
        headers=auth_headers,
        files={"file": ("x.exe", BytesIO(b"MZ"), "application/x-msdownload")},
    )
    assert bad_type.status_code == 400

    too_big = client.post(
        f"/api/itsm/incident/{incident_id}/attachments",
        headers=auth_headers,
        files={
            "file": (
                "big.txt",
                BytesIO(b"x" * (5 * 1024 * 1024 + 1)),
                "text/plain",
            )
        },
    )
    assert too_big.status_code == 413


def test_sla_business_hours_and_holiday_clock_math() -> None:
    cal = {
        "timezone": "UTC",
        "business_hours_only": True,
        "business_hours_start": "09:00",
        "business_hours_end": "17:00",
        "business_days": ["mon", "tue", "wed", "thu", "fri"],
        "holidays": ["2026-11-26"],  # Thursday
    }
    # Wednesday 16:00 + 120 business minutes → Thursday holiday skipped → Friday 10:00
    start = datetime(2026, 11, 25, 16, 0, tzinfo=timezone.utc)
    due = add_business_minutes(start, 120, cal)
    assert due == datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)

    # 24x7 unchanged
    wall = compute_due_at(
        started_at=start,
        target_minutes=60,
        calendar={"timezone": "UTC", "business_hours_only": False},
    )
    assert wall == start + timedelta(minutes=60)

    elapsed = business_seconds_between(
        datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc),
        cal,
    )
    assert elapsed == 3600


def test_sla_policy_applies_business_hours_due_at(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    policy = client.post(
        "/api/itsm/sla/policies",
        headers=auth_headers,
        json={
            "name": "Biz hours SLA",
            "applies_to": "incident",
            "active": True,
            "priority_order": 10,
            "match": {},
            "pause_on_statuses": ["on_hold"],
            "targets": [
                {
                    "metric": "response",
                    "priority_targets": [{"priority": "p3", "minutes": 60}],
                }
            ],
            "calendar": {
                "timezone": "UTC",
                "business_hours_only": True,
                "business_hours_start": "09:00",
                "business_hours_end": "17:00",
                "holidays": ["2099-01-01"],
            },
        },
    )
    assert policy.status_code == 201, policy.text
    assert policy.json()["calendar"]["business_hours_only"] is True
    assert "2099-01-01" in (policy.json()["calendar"].get("holidays") or [])

    inc = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={"title": "Clock test", "priority": "p3"},
    )
    assert inc.status_code == 201, inc.text
    tracking = client.get(
        "/api/itsm/sla/tracking",
        headers=auth_headers,
        params={
            "ticket_type": "incident",
            "ticket_id": inc.json()["incident_id"],
        },
    )
    assert tracking.status_code == 200, tracking.text
    items = tracking.json()["items"]
    assert items
    row = items[0]
    assert row.get("calendar_snapshot", {}).get("business_hours_only") is True
    assert row.get("due_at")


def test_watchers_notified_on_status_change(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "Watch me",
            "priority": "p3",
            "assignee_user_id": "assignee-1",
            "watcher_user_ids": ["watcher-1", "watcher-2"],
            "cc_emails": ["stakeholder@example.com"],
        },
    )
    assert created.status_code == 201, created.text
    doc = created.json()
    assert doc["watcher_user_ids"] == ["watcher-1", "watcher-2"]
    assert doc["cc_emails"] == ["stakeholder@example.com"]

    transitioned = client.post(
        f"/api/itsm/incidents/{doc['incident_id']}/transition",
        headers=auth_headers,
        json={"status": "in_progress"},
    )
    assert transitioned.status_code == 200, transitioned.text

    from app.db import get_itsm_database

    notifs = list(get_itsm_database()["itsm_notifications"].find({}))
    recipients = {n.get("recipient_user_id") for n in notifs}
    assert "assignee-1" in recipients
    assert "watcher-1" in recipients
    assert "watcher-2" in recipients


def test_related_ticket_validation_and_clickthrough_fields(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    bad = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "Bad related",
            "priority": "p3",
            "problem_id": "PRB-DOES-NOT-EXIST",
        },
    )
    assert bad.status_code == 400, bad.text
    body = bad.json()
    blob = str(body).lower()
    assert "not found" in blob or "problem" in blob, body

    problem = client.post(
        "/api/itsm/problems",
        headers=auth_headers,
        json={"title": "Root cause", "priority": "p3"},
    )
    assert problem.status_code == 201, problem.text
    problem_id = problem.json()["problem_id"]

    ok = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "Linked incident",
            "priority": "p3",
            "problem_id": problem_id,
            "assignment_group": "NOC",
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["problem_id"] == problem_id

    change_bad = client.post(
        "/api/itsm/changes",
        headers=auth_headers,
        json={
            "title": "Bad change links",
            "priority": "p3",
            "related_incident_ids": ["INC-MISSING"],
        },
    )
    assert change_bad.status_code == 400
