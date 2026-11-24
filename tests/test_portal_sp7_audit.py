"""Service Portal SP7 — audit + entitlements + form hardening (0.97.0)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.db import get_itsm_database
from app.portal.services.form_validate import FormValidationError, validate_form_values
from app.services import entitlements as entitlements_service

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_portal_sp7() -> None:
    assert __version__ == "0.97.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.97.0"' in html


def test_path_and_username_hardening() -> None:
    schema = {
        "version": 1,
        "fields": [
            {"name": "p", "type": "path", "label": "Path", "required": True},
            {"name": "u", "type": "username", "label": "User", "required": True},
        ],
    }
    with pytest.raises(FormValidationError):
        validate_form_values(schema, {"p": "/tmp/../etc/passwd", "u": "alice"})
    with pytest.raises(FormValidationError):
        validate_form_values(schema, {"p": "/tmp/x;rm", "u": "alice"})
    with pytest.raises(FormValidationError):
        validate_form_values(schema, {"p": "/tmp/ok", "u": "bad;user"})
    ok = validate_form_values(schema, {"p": "/var/tmp/ok", "u": "alice"})
    assert ok["u"] == "alice"


def test_portal_entitlement_keys_present() -> None:
    plans = {p["plan_code"]: p for p in entitlements_service.list_plans()}
    assert "sp_open_requests" in plans["starter"]["limits"]
    assert "sp_catalog_items" in plans["starter"]["limits"]
    assert "sp_executions_per_day" in plans["starter"]["limits"]
    assert plans["legacy_unlimited"]["limits"]["sp_open_requests"] is None


@pytest.mark.usefixtures("clean_db")
def test_submit_writes_portal_audit_event(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200, seed.text
    item = next(
        i
        for i in client.get("/api/portal/catalog", headers=auth_headers).json()["items"]
        if i["key"] == "generic.daily.access_request"
    )
    created = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": item["item_id"],
            "form_values": {
                "who": "frank",
                "what": "vpn",
                "why": "audit test",
                "duration_days": 2,
            },
            "submit": True,
        },
    )
    assert created.status_code == 200, created.text
    request_id = created.json()["request_id"]

    listed = client.get(
        "/api/portal/audit",
        headers=auth_headers,
        params={"request_id": request_id},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] >= 1
    assert any(
        e.get("action") == "portal.request.submit" for e in listed.json()["items"]
    )

    db = get_itsm_database()
    assert db is not None
    docs = list(db["sp_audit_events"].find({"request_id": request_id}))
    assert docs
