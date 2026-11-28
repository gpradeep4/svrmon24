"""Service Portal SP4 — Change-driven approval sync (0.99.14)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_portal_sp4() -> None:
    assert __version__ == "0.99.14"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.14"' in html
    assert "portal/approvals.js?v=0.99.14" in html


def test_portal_approvals_fe_markers() -> None:
    js = Path("frontend/static/js/portal/approvals.js").read_text(encoding="utf-8")
    assert "SVRMON24PortalApprovals" in js
    assert "/api/portal/changes" in js
    assert "Open in ITSM" in js
    assert "itsm-changes" in js


@pytest.mark.usefixtures("clean_db")
def test_change_status_sync_approves_and_rejects(
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
                "username": "bob",
                "groups": "users",
                "create_home": True,
                "target_ci": "srv-demo-1",
            },
            "submit": True,
        },
    )
    assert created.status_code == 200, created.text
    req = created.json()
    assert req["status"] == "pending_approval"
    change_id = req["change_id"]
    request_id = req["request_id"]

    listed = client.get("/api/portal/changes", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["approval_sot"] == "itsm_change"
    assert body["decide_surface"] == "itsm"
    assert any(r["request_id"] == request_id for r in body["items"])

    # Approve via ITSM Change transition (SoT) — not a Portal decide API.
    transition = client.post(
        f"/api/itsm/changes/{change_id}/transition",
        headers=auth_headers,
        json={"status": "approved", "comment": "CAB ok"},
    )
    assert transition.status_code == 200, transition.text

    synced = client.post(
        f"/api/portal/changes/{request_id}/sync",
        headers=auth_headers,
    )
    assert synced.status_code == 200, synced.text
    # SP6 auto-enqueues SIMULATED runs on approve → request advances to queued.
    assert synced.json()["status"] == "queued"
    assert synced.json()["change_status_snapshot"] == "approved"

    # Second request → reject path
    created2 = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": item["item_id"],
            "form_values": {
                "username": "carol",
                "groups": "users",
                "create_home": False,
                "target_ci": "srv-demo-2",
            },
            "submit": True,
        },
    )
    assert created2.status_code == 200, created2.text
    req2 = created2.json()
    reject = client.post(
        f"/api/itsm/changes/{req2['change_id']}/transition",
        headers=auth_headers,
        json={"status": "rejected", "comment": "nope"},
    )
    assert reject.status_code == 200, reject.text

    batch = client.post("/api/portal/changes/sync", headers=auth_headers)
    assert batch.status_code == 200, batch.text
    assert batch.json()["synced"] >= 1

    detail = client.get(
        f"/api/portal/requests/{req2['request_id']}?refresh_change=true",
        headers=auth_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "rejected"
    assert detail.json()["change_status_snapshot"] == "rejected"


@pytest.mark.usefixtures("clean_db")
def test_portal_has_no_decide_endpoint(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """OD-2: Portal must not own approval decide — only ITSM does."""
    resp = client.post(
        "/api/portal/approvals/decide",
        headers=auth_headers,
        json={"decision": "approve"},
    )
    assert resp.status_code in (404, 405)
