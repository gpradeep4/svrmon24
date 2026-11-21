"""ITSM Incident Management — dual-DB foundation + CRUD / transitions / CI links."""

from __future__ import annotations

from app import __version__
from app.config import get_settings
from app.db import get_database, get_itsm_database
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_itsm() -> None:
    # Shared package version — N5 CMDB↔ITSM deep-links owns the 0.58.0 bump.
    assert __version__ == "0.58.0"


def test_dual_db_defaults_and_fallback(monkeypatch) -> None:
    monkeypatch.delenv("MONGODB_CMDB_DB", raising=False)
    monkeypatch.setenv("MONGODB_DB", "svrmon24_legacy_probe")
    monkeypatch.setenv("MONGODB_ITSM_DB", "svrmon-itsm-probe")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.cmdb_database_name == "svrmon24_legacy_probe"
    assert settings.itsm_database_name == "svrmon-itsm-probe"
    get_settings.cache_clear()


def test_cmdb_db_override(monkeypatch) -> None:
    monkeypatch.setenv("MONGODB_DB", "svrmon24")
    monkeypatch.setenv("MONGODB_CMDB_DB", "svrmon-cmdb")
    monkeypatch.setenv("MONGODB_ITSM_DB", "svrmon-itsm")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.cmdb_database_name == "svrmon-cmdb"
    assert settings.itsm_database_name == "svrmon-itsm"
    get_settings.cache_clear()


def test_itsm_and_cmdb_are_separate_handles(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    cmdb = get_database()
    itsm = get_itsm_database()
    assert cmdb.name != itsm.name
    assert itsm.name.endswith("itsm_test") or itsm.name == "svrmon-itsm"


def _create_component(client: TestClient, headers: dict[str, str]) -> str:
    payload = {
        "component_type": "Server",
        "name": "itsm-ci-web",
        "hostname": "itsm-ci-web.example",
        "environment": "prod",
        "status": "active",
        "os_family": "linux",
    }
    response = client.post("/api/components", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["component_id"]


def test_incident_crud_transition_activity_and_ci_link(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    component_id = _create_component(client, auth_headers)

    created = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "Billing API 500s",
            "description": "Elevated error rate",
            "priority": "p2",
            "category": "application",
            "ci_links": [{"component_id": component_id}],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["tenant_id"]
    assert body["incident_id"].startswith("INC-")
    assert body["number_display"].startswith("INC-")
    assert body["status"] == "new"
    assert body["ci_links"][0]["component_id"] == component_id
    assert body["ci_links"][0]["name_snapshot"]

    incident_id = body["incident_id"]

    listed = client.get("/api/itsm/incidents", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] >= 1

    got = client.get(f"/api/itsm/incidents/{incident_id}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["title"] == "Billing API 500s"

    patched = client.patch(
        f"/api/itsm/incidents/{incident_id}",
        headers=auth_headers,
        json={"assignee_user_id": "ops.alice"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["assignee_user_id"] == "ops.alice"

    transitioned = client.post(
        f"/api/itsm/incidents/{incident_id}/transition",
        headers=auth_headers,
        json={"status": "in_progress", "comment": "Investigating"},
    )
    assert transitioned.status_code == 200, transitioned.text
    assert transitioned.json()["status"] == "in_progress"

    bad = client.post(
        f"/api/itsm/incidents/{incident_id}/transition",
        headers=auth_headers,
        json={"status": "closed"},
    )
    assert bad.status_code == 409

    activities = client.get(
        f"/api/itsm/incident/{incident_id}/activities",
        headers=auth_headers,
    )
    assert activities.status_code == 200, activities.text
    types = {a["activity_type"] for a in activities.json()["items"]}
    assert "created" in types
    assert "status_change" in types

    comment = client.post(
        f"/api/itsm/incident/{incident_id}/activities",
        headers=auth_headers,
        json={"message": "Looking at nginx error log", "activity_type": "comment"},
    )
    assert comment.status_code == 201, comment.text

    # Incident documents live in ITSM DB, not CMDB DB.
    assert get_itsm_database()["itsm_incidents"].count_documents({}) >= 1
    assert get_database()["itsm_incidents"].count_documents({}) == 0

    dash = client.get("/api/itsm/dashboard/summary", headers=auth_headers)
    assert dash.status_code == 200, dash.text
    assert dash.json()["open_incidents"] >= 1


def test_ci_link_rejects_missing_component(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "Missing CI",
            "ci_links": [{"component_id": "does-not-exist"}],
        },
    )
    assert created.status_code == 404


def test_cross_tenant_incident_is_404(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={"title": "Tenant A incident"},
    )
    assert created.status_code == 201
    incident_id = created.json()["incident_id"]
    tenant_id = created.json()["tenant_id"]

    # Plant a foreign-tenant clone that shares the id.
    foreign = dict(get_itsm_database()["itsm_incidents"].find_one({"incident_id": incident_id}))
    foreign.pop("_id", None)
    foreign["tenant_id"] = "tenant-other-org"
    foreign["incident_id"] = "INC-FOREIGN01"
    foreign["number"] = 999001
    foreign["number_display"] = "INC-999001"
    get_itsm_database()["itsm_incidents"].insert_one(foreign)

    missing = client.get("/api/itsm/incidents/INC-FOREIGN01", headers=auth_headers)
    assert missing.status_code == 404

    # Own tenant still visible.
    own = client.get(f"/api/itsm/incidents/{incident_id}", headers=auth_headers)
    assert own.status_code == 200
    assert own.json()["tenant_id"] == tenant_id


def test_frontend_itsm_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.58.0"' in html
    assert 'data-tab="itsm-incidents"' in html
    assert 'data-tab="itsm-dashboard"' in html
    assert 'id="navItsmSection"' in html
    assert "/static/js/itsm/incidents.js" in html
    assert "/static/js/itsm/deeplinks.js" in html
    assert "/static/css/itsm.css" in html
    assert 'id="itsmIncCiFilter"' in html
    assert 'id="itsmIncImpactPanel"' in html
