"""CMDB C3 — People + Work Info (+ attachments) (0.99.8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from tests.frontend_paths import FRONTEND_INDEX

REPO = Path(__file__).resolve().parents[1]
CI_DETAIL_JS = REPO / "frontend" / "static" / "js" / "cmdb" / "ci-detail.js"
DEEPLINKS_JS = REPO / "frontend" / "static" / "js" / "itsm" / "deeplinks.js"
CMDB_CSS = REPO / "frontend" / "static" / "css" / "cmdb.css"
CMDB_JS = REPO / "frontend" / "static" / "js" / "cmdb.js"
PEOPLE_SVC = REPO / "app" / "cmdb" / "services" / "people.py"
WORK_SVC = REPO / "app" / "cmdb" / "services" / "work_info.py"


def test_c3_version_bump() -> None:
    assert __version__ == "0.99.8"


def test_frontend_c3_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.8"' in html
    assert "cmdb/ci-detail.js?v=0.99.8" in html

    js = CI_DETAIL_JS.read_text(encoding="utf-8")
    assert 'id: "people", label: "People", active: true' in js
    assert 'id: "work-info", label: "Work Info", active: true' in js
    assert 'registerTabHook("people"' in js
    assert 'registerTabHook("work-info"' in js
    assert "/api/components/" in js and "/people" in js
    assert "/work-info" in js
    assert "itsm_ticket_ref" in js
    assert "Open in ITSM" in js
    assert "Create related incident" in js
    assert "people/primary" in js

    deeplinks = DEEPLINKS_JS.read_text(encoding="utf-8")
    assert "openCreateRelated" in deeplinks
    assert "assignmentGroup" in deeplinks

    css = CMDB_CSS.read_text(encoding="utf-8")
    assert ".ci-people-actions" in css
    assert ".ci-work-layout" in css

    cmdb = CMDB_JS.read_text(encoding="utf-8")
    assert "FormData" in cmdb

    work = WORK_SVC.read_text(encoding="utf-8")
    assert "cmdb_ci_attachments" in work
    assert "MongoDB Binary" in work or "Binary" in work
    assert "MAX_ATTACHMENT_BYTES" in work

    people = PEOPLE_SVC.read_text(encoding="utf-8")
    assert "cmdb_ci_people" in people


def _create_server(client: TestClient, headers: dict[str, str], name: str) -> str:
    created = client.post(
        "/api/components",
        headers=headers,
        json={
            "component_type": "Server",
            "name": name,
            "hostname": name,
            "environment": "Development",
            "status": "active",
            "os_family": "Linux",
            "os_version": "8.9",
            "ip_address": "10.3.3.1",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["component_id"]


def test_people_crud_primary_and_assignment_hint(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    srv = _create_server(client, auth_headers, "c3-people-srv.example.com")

    empty = client.get(
        f"/api/components/{srv}/people", headers=auth_headers
    )
    assert empty.status_code == 200
    assert empty.json()["total"] == 0

    created = client.post(
        f"/api/components/{srv}/people",
        headers=auth_headers,
        json={
            "party_type": "support_group",
            "party_id": "grp-sis-ops",
            "display_name": "UOB Group→SIS Ops",
            "role": "managed_by",
            "primary_contact": True,
            "assignment_enabled": True,
            "notify_on_unavailability": True,
            "access_permission": False,
        },
    )
    assert created.status_code == 201, created.text
    link = created.json()
    assert link["link_id"].startswith("plk-")
    assert link["primary_contact"] is True
    link_id = link["link_id"]

    # Second primary clears the first.
    other = client.post(
        f"/api/components/{srv}/people",
        headers=auth_headers,
        json={
            "party_type": "person",
            "party_id": "user-alice",
            "display_name": "Alice Ops",
            "role": "supported_by",
            "primary_contact": True,
        },
    )
    assert other.status_code == 201, other.text

    listed = client.get(f"/api/components/{srv}/people", headers=auth_headers)
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert listed.json()["total"] == 2
    primaries = [i for i in items if i["primary_contact"]]
    assert len(primaries) == 1
    assert primaries[0]["party_id"] == "user-alice"

    # Restore support group as primary for assignment hint.
    patched = client.patch(
        f"/api/components/{srv}/people/{link_id}",
        headers=auth_headers,
        json={"primary_contact": True},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["primary_contact"] is True

    primary = client.get(
        f"/api/components/{srv}/people/primary", headers=auth_headers
    )
    assert primary.status_code == 200
    body = primary.json()
    assert body["primary"]["party_id"] == "grp-sis-ops"
    assert body["assignment_hint"]["assignment_group"] == "UOB Group→SIS Ops"

    deleted = client.delete(
        f"/api/components/{srv}/people/{other.json()['link_id']}",
        headers=auth_headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    # Cross-tenant / missing CI → 404
    missing = client.get(
        "/api/components/srv-does-not-exist/people", headers=auth_headers
    )
    assert missing.status_code == 404


def test_work_info_crud_attachment_itsm_ref_and_locked(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    srv = _create_server(client, auth_headers, "c3-work-srv.example.com")

    empty = client.get(
        f"/api/components/{srv}/work-info", headers=auth_headers
    )
    assert empty.status_code == 200
    assert empty.json()["total"] == 0

    created = client.post(
        f"/api/components/{srv}/work-info",
        headers=auth_headers,
        json={
            "work_info_type": "general",
            "source": "Web Client",
            "summary": "Patched firmware notes",
            "notes": "Applied patch set A",
            "locked": False,
            "view_access": "internal",
            "itsm_ticket_ref": {"module": "incident", "ticket_id": "INC-C3-DEMO"},
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()
    wid = row["work_info_id"]
    assert wid.startswith("wi-")
    assert row["itsm_ticket_ref"]["ticket_id"] == "INC-C3-DEMO"
    assert row["attachment_count"] == 0

    # Invalid ITSM module rejected
    bad_ref = client.post(
        f"/api/components/{srv}/work-info",
        headers=auth_headers,
        json={
            "summary": "bad",
            "itsm_ticket_ref": {"module": "cmdb", "ticket_id": "X"},
        },
    )
    assert bad_ref.status_code == 422

    upload = client.post(
        f"/api/components/{srv}/work-info/{wid}/attachments",
        headers=auth_headers,
        files={"file": ("note.txt", b"hello c3", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    att = upload.json()
    assert att["attachment_id"].startswith("CATT-")
    assert att["filename"] == "note.txt"
    assert "content" not in att

    detail = client.get(
        f"/api/components/{srv}/work-info/{wid}", headers=auth_headers
    )
    assert detail.status_code == 200
    d = detail.json()
    assert d["attachment_count"] == 1
    assert len(d["attachments"]) == 1

    content = client.get(
        f"/api/components/{srv}/work-info/{wid}/attachments/"
        f"{att['attachment_id']}/content",
        headers=auth_headers,
    )
    assert content.status_code == 200
    assert content.content == b"hello c3"

    listed = client.get(
        f"/api/components/{srv}/work-info", headers=auth_headers
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["attachment_count"] == 1

    # Locked entry rejects delete
    locked = client.post(
        f"/api/components/{srv}/work-info",
        headers=auth_headers,
        json={"summary": "Locked note", "locked": True},
    )
    assert locked.status_code == 201
    locked_id = locked.json()["work_info_id"]
    deny = client.delete(
        f"/api/components/{srv}/work-info/{locked_id}",
        headers=auth_headers,
    )
    assert deny.status_code == 409

    # Unlocked delete cascades attachments
    deleted = client.delete(
        f"/api/components/{srv}/work-info/{wid}",
        headers=auth_headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True
    gone = client.get(
        f"/api/components/{srv}/work-info/{wid}", headers=auth_headers
    )
    assert gone.status_code == 404
    gone_att = client.get(
        f"/api/components/{srv}/work-info/{wid}/attachments/"
        f"{att['attachment_id']}/content",
        headers=auth_headers,
    )
    assert gone_att.status_code == 404


def test_c3_tabs_remain_active_alongside_c4() -> None:
    js = CI_DETAIL_JS.read_text(encoding="utf-8")
    assert 'id: "people", label: "People", active: true' in js
    assert 'id: "work-info", label: "Work Info", active: true' in js
    # C4 activates the remaining CI detail tabs (asserted in test_cmdb_c4_*).
    assert 'id: "contracts", label: "Contracts", active: true' in js
    assert 'id: "outage", label: "Outage", active: true' in js
    assert 'id: "impacted-areas", label: "Impacted Areas", active: true' in js
