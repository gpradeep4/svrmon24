"""Service Portal SP8 — incident link + ITSM deep-link UX (0.94.0)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_portal_sp8() -> None:
    assert __version__ == "0.94.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.94.0"' in html


def test_portal_sp8_fe_markers() -> None:
    req = Path("frontend/static/js/portal/requests.js").read_text(encoding="utf-8")
    assert "openItsmChange" in req
    assert "openItsmIncident" in req
    assert "link-incident" in req
    cat = Path("frontend/static/js/portal/catalog.js").read_text(encoding="utf-8")
    assert "linked_incident_id" in cat
    assert "does not auto-approve" in cat.lower() or "Approvals happen in ITSM" in cat


@pytest.mark.usefixtures("clean_db")
def test_link_incident_to_portal_request(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Create an ITSM incident first.
    inc = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "Portal link target",
            "description": "For SP8",
            "priority": "p3",
        },
    )
    assert inc.status_code in (200, 201), inc.text
    incident_id = inc.json()["incident_id"]

    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200
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
                "who": "gina",
                "what": "vpn",
                "why": "sp8",
                "duration_days": 1,
            },
            "submit": True,
        },
    )
    assert created.status_code == 200, created.text
    request_id = created.json()["request_id"]

    linked = client.post(
        f"/api/portal/requests/{request_id}/link-incident",
        headers=auth_headers,
        json={"linked_incident_id": incident_id},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["linked_incident_id"] == incident_id

    # Unknown incident rejected.
    bad = client.post(
        f"/api/portal/requests/{request_id}/link-incident",
        headers=auth_headers,
        json={"linked_incident_id": "INC-DOES-NOT-EXIST"},
    )
    assert bad.status_code == 404
