"""File Monitoring API + UI markers — SIMULATED mode only."""

from __future__ import annotations

from app import __version__
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX, FRONTEND_STATIC


def test_version_patch_for_file_monitoring() -> None:
    assert __version__ == "0.70.0"


def test_meta_is_simulated(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    response = client.get("/api/file-monitoring/meta", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["execution_mode"] == "SIMULATED"
    assert body["demo_only"] is True
    assert body["live_watching"] is False
    assert "SIMULATED" in body["banner"]
    assert body["tenant_id"]


def test_list_targets_seeds_demo_and_is_tenant_scoped(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    response = client.get("/api/file-monitoring/targets", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["execution_mode"] == "SIMULATED"
    assert body["live_watching"] is False
    assert body["total"] >= 4
    assert len(body["items"]) >= 4
    for item in body["items"]:
        assert item["execution_mode"] == "SIMULATED"
        assert item["tenant_id"] == body["tenant_id"]
        assert item["watch_id"].startswith("fw-demo-")
        assert item.get("latest_actor")
        assert item.get("latest_changed_at")


def test_get_target_and_versions(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    listed = client.get("/api/file-monitoring/targets", headers=auth_headers)
    assert listed.status_code == 200
    watch_id = listed.json()["items"][0]["watch_id"]

    detail = client.get(
        f"/api/file-monitoring/targets/{watch_id}", headers=auth_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["watch_id"] == watch_id
    assert detail.json()["execution_mode"] == "SIMULATED"

    versions = client.get(
        f"/api/file-monitoring/targets/{watch_id}/versions",
        headers=auth_headers,
    )
    assert versions.status_code == 200, versions.text
    body = versions.json()
    assert body["watch_id"] == watch_id
    assert body["total"] >= 1
    assert body["execution_mode"] == "SIMULATED"
    for ev in body["items"]:
        assert ev["data_source"] == "SYNTHETIC_DEMO"
        assert ev["execution_mode"] == "SIMULATED"
        assert ev["actor"]
        assert ev["changed_at"]
        assert "not a live" in (ev.get("note") or "").lower()

    event_id = body["items"][0]["event_id"]
    one = client.get(
        f"/api/file-monitoring/versions/{event_id}", headers=auth_headers
    )
    assert one.status_code == 200, one.text
    assert one.json()["event_id"] == event_id


def test_unknown_target_404(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    response = client.get(
        "/api/file-monitoring/targets/fw-does-not-exist",
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_status_filter(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    response = client.get(
        "/api/file-monitoring/targets",
        headers=auth_headers,
        params={"status": "paused"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 1
    assert all(item["status"] == "paused" for item in body["items"])


def test_unauthenticated_rejected(client: TestClient, clean_db) -> None:
    response = client.get("/api/file-monitoring/targets")
    assert response.status_code in {401, 403}


def test_cross_tenant_target_hidden(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from datetime import datetime, timezone

    from app.db import get_database, get_monitor_database
    from app.services import tenants as tenants_service
    from app.tenancy import MIGRATION_TENANT_ID

    tenants_service.ensure_migration_tenant()
    # Ensure demo seed in migration tenant
    client.get("/api/file-monitoring/targets", headers=auth_headers)

    other_id = "tenant-fm-other"
    now = datetime.now(timezone.utc)
    db = get_database()
    db["tenants"].update_one(
        {"tenant_id": other_id},
        {
            "$setOnInsert": {
                "tenant_id": other_id,
                "display_name": "FM Other",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    get_monitor_database()["file_watch_targets"].insert_one(
        {
            "watch_id": "fw-other-secret",
            "path": "/secret/other.conf",
            "label": "Other tenant secret",
            "status": "active",
            "execution_mode": "SIMULATED",
            "latest_version": 1,
            "latest_actor": "other.user",
            "latest_changed_at": now,
            "tenant_id": other_id,
            "created_at": now,
            "updated_at": now,
        }
    )

    listed = client.get("/api/file-monitoring/targets", headers=auth_headers)
    assert listed.status_code == 200
    ids = {i["watch_id"] for i in listed.json()["items"]}
    assert "fw-other-secret" not in ids
    assert listed.json()["tenant_id"] == MIGRATION_TENANT_ID

    missing = client.get(
        "/api/file-monitoring/targets/fw-other-secret", headers=auth_headers
    )
    assert missing.status_code == 404


def test_file_monitoring_read_in_permission_catalog(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.permissions import PERM_FILE_MONITORING_READ
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    resp = client.get("/api/permissions", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    keys = {p["permission"] for p in body["permissions"]}
    assert PERM_FILE_MONITORING_READ in keys
    assert PERM_FILE_MONITORING_READ in body["current"]["permissions"]
    assert PERM_FILE_MONITORING_READ in body["matrix"]["viewer"]


def test_frontend_file_monitoring_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "cmdb.js").read_text(encoding="utf-8")
    css = (FRONTEND_STATIC / "css" / "cmdb.css").read_text(encoding="utf-8")

    assert 'data-tab="file-monitoring"' in html
    assert 'data-fm-module="1"' in html
    assert 'data-fm-simulated="1"' in html
    assert 'id="tab-file-monitoring"' in html
    assert "File Monitoring (DEMO / SIMULATED)" in html
    assert 'id="fmTargetsBody"' in html
    assert 'id="fmVersionsBody"' in html
    assert 'id="fmDrawer"' in html
    assert "loadFileMonitoringTargets" in js
    assert "openFileMonitoringDetail" in js
    assert "/api/file-monitoring/targets" in js
    assert ".fm-drawer" in css
    assert 'content="0.70.0"' in html
