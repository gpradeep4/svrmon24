"""Service Portal SP3 — requests lifecycle + ITSM Change on submit (0.99.15)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.db import get_itsm_database

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_portal_sp3() -> None:
    assert __version__ == "0.99.15"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.15"' in html
    assert "portal/requests.js?v=0.99.15" in html


def test_portal_requests_fe_markers() -> None:
    js = Path("frontend/static/js/portal/requests.js").read_text(encoding="utf-8")
    assert "SVRMON24PortalRequests" in js
    assert "/api/portal/requests" in js
    catalog = Path("frontend/static/js/portal/catalog.js").read_text(encoding="utf-8")
    assert "submitNewRequest" in catalog


@pytest.mark.usefixtures("clean_db")
def test_request_submit_creates_itsm_change(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200, seed.text

    listed = client.get("/api/portal/catalog", headers=auth_headers)
    assert listed.status_code == 200
    item = next(i for i in listed.json()["items"] if i["key"] == "os.user.create")

    created = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": item["item_id"],
            "collect_mode": "agentless",
            "form_values": {
                "username": "alice",
                "groups": "users",
                "create_home": True,
                "target_ci": "srv-demo-1",
            },
            "submit": True,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "pending_approval"
    assert body["change_id"]
    assert body["change_type_key"] == "sp.os.user.create"
    assert body["change_status_snapshot"] == "submitted"
    assert body["collect_mode"] == "agentless"
    assert body["item_key_snapshot"] == "os.user.create"

    change = client.get(
        f"/api/itsm/changes/{body['change_id']}", headers=auth_headers
    )
    assert change.status_code == 200, change.text
    chg = change.json()
    assert chg["status"] == "submitted"
    assert chg["change_type"] == "normal"
    assert chg["category"] == "service_portal"
    assert body["request_id"] in (chg.get("title") or "")

    listed_req = client.get("/api/portal/requests", headers=auth_headers)
    assert listed_req.status_code == 200
    assert listed_req.json()["total"] >= 1
    assert any(r["request_id"] == body["request_id"] for r in listed_req.json()["items"])

    detail = client.get(
        f"/api/portal/requests/{body['request_id']}?refresh_change=true",
        headers=auth_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["change_status_snapshot"] == "submitted"


@pytest.mark.usefixtures("clean_db")
def test_request_draft_then_submit_and_cancel(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200
    item = next(
        i
        for i in client.get("/api/portal/catalog", headers=auth_headers).json()["items"]
        if i["key"] == "generic.daily.access_request"
    )

    draft = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": item["item_id"],
            "form_values": {
                "who": "alice",
                "what": "vpn access",
                "why": "project work",
                "duration_days": 7,
            },
            "submit": False,
        },
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["status"] == "draft"
    request_id = draft.json()["request_id"]

    submitted = client.post(
        f"/api/portal/requests/{request_id}/submit",
        headers=auth_headers,
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "pending_approval"
    assert submitted.json()["change_id"]
    change_id = submitted.json()["change_id"]

    cancelled = client.post(
        f"/api/portal/requests/{request_id}/cancel",
        headers=auth_headers,
        json={"comment": "no longer needed"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    chg = client.get(f"/api/itsm/changes/{change_id}", headers=auth_headers)
    assert chg.status_code == 200
    assert chg.json()["status"] == "cancelled"

    db = get_itsm_database()
    assert db is not None
    docs = list(db["sp_requests"].find({"request_id": request_id}))
    assert len(docs) == 1
    assert docs[0]["status"] == "cancelled"


@pytest.mark.usefixtures("clean_db")
def test_request_rejects_bad_form(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200
    item = next(
        i
        for i in client.get("/api/portal/catalog", headers=auth_headers).json()["items"]
        if i["key"] == "os.user.create"
    )

    bad_form = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": item["item_id"],
            "form_values": {"username": "BAD USER"},
            "submit": False,
        },
    )
    assert bad_form.status_code == 400, bad_form.text
    err = bad_form.json().get("error") or {}
    details = err.get("details") or bad_form.json().get("detail") or {}
    if isinstance(details, dict):
        assert "field_errors" in details, bad_form.text
    else:
        assert "form validation" in str(err.get("message") or "").lower()
