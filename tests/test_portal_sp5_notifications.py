"""Service Portal SP5 — Change/request notification deep-links (0.99.0)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.db import get_itsm_database

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_portal_sp5() -> None:
    assert __version__ == "0.99.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.0"' in html


def test_portal_notification_fe_deep_link_markers() -> None:
    js = Path("frontend/static/js/itsm/notifications.js").read_text(encoding="utf-8")
    assert "portal_request_id" in js
    assert "sp-approvals" in js
    assert "sp-my-requests" in js


@pytest.mark.usefixtures("clean_db")
def test_submit_and_decision_emit_portal_linked_notifications(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200, seed.text
    item = next(
        i
        for i in client.get("/api/portal/catalog", headers=auth_headers).json()["items"]
        if i["key"] == "os.user.create"
    )

    created = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": item["item_id"],
            "form_values": {
                "username": "dave",
                "groups": "users",
                "create_home": True,
                "target_ci": "srv-demo-1",
            },
            "submit": True,
        },
    )
    assert created.status_code == 200, created.text
    req = created.json()
    request_id = req["request_id"]
    change_id = req["change_id"]

    db = get_itsm_database()
    assert db is not None
    submitted_notes = list(
        db["itsm_notifications"].find({"portal_request_id": request_id})
    )
    assert submitted_notes, "expected submit notification with portal_request_id"
    assert any(n.get("ticket_id") == change_id for n in submitted_notes)
    assert any(n.get("ticket_type") == "change" for n in submitted_notes)

    transition = client.post(
        f"/api/itsm/changes/{change_id}/transition",
        headers=auth_headers,
        json={"status": "approved", "comment": "ok"},
    )
    assert transition.status_code == 200, transition.text

    synced = client.post(
        f"/api/portal/changes/{request_id}/sync",
        headers=auth_headers,
    )
    assert synced.status_code == 200, synced.text
    # SP6 auto-enqueues on approve → request status advances to queued.
    assert synced.json()["status"] == "queued"

    decided = list(
        db["itsm_notifications"].find(
            {
                "portal_request_id": request_id,
                "event_type": "approval_decided",
            }
        )
    )
    assert decided, "expected decision notification linked to portal request"
    assert decided[0].get("ticket_id") == change_id
