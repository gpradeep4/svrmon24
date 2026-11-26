"""Monitoring M3 — File Monitoring data rehome to svrmon-monitor (0.99.3)."""

from __future__ import annotations

from datetime import datetime, timezone

from app import __version__
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_monitor_m3() -> None:
    assert __version__ == "0.99.3"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.3"' in html


def test_meta_reports_monitor_database(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.config import get_settings

    response = client.get("/api/file-monitoring/meta", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["execution_mode"] == "SIMULATED"
    assert body["live_watching"] is False
    assert body["monitor_database"] == get_settings().monitor_database_name
    assert body["database"] == get_settings().monitor_database_name


def test_seed_writes_to_monitor_db(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.db import get_database, get_monitor_database
    from app.tenancy import MIGRATION_TENANT_ID, tenant_filter

    response = client.get("/api/file-monitoring/targets", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 4

    monitor = get_monitor_database()
    cmdb = get_database()
    filt = tenant_filter(MIGRATION_TENANT_ID)
    assert monitor["file_watch_targets"].count_documents(filt) >= 4
    assert monitor["file_version_events"].count_documents(filt) >= 1
    # Fresh seed should not write to CMDB after M3.
    assert cmdb["file_watch_targets"].count_documents(filt) == 0


def test_dual_read_migrates_from_cmdb_when_monitor_empty(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.db import get_database, get_monitor_database
    from app.services import tenants as tenants_service
    from app.tenancy import MIGRATION_TENANT_ID, tenant_filter

    tenants_service.ensure_migration_tenant()
    now = datetime.now(timezone.utc)
    cmdb = get_database()
    monitor = get_monitor_database()
    filt = tenant_filter(MIGRATION_TENANT_ID)

    # Pre-populate legacy CMDB rows only.
    cmdb["file_watch_targets"].insert_one(
        {
            "watch_id": "fw-legacy-cmdb",
            "path": "/etc/legacy.conf",
            "label": "Legacy CMDB watch",
            "host": "legacy-host",
            "status": "active",
            "execution_mode": "SIMULATED",
            "latest_version": 1,
            "latest_actor": "ops.legacy",
            "latest_changed_at": now,
            "tenant_id": MIGRATION_TENANT_ID,
            "created_at": now,
            "updated_at": now,
        }
    )
    cmdb["file_version_events"].insert_one(
        {
            "event_id": "fve-legacy-cmdb-v1",
            "watch_id": "fw-legacy-cmdb",
            "path": "/etc/legacy.conf",
            "version": 1,
            "change_kind": "created",
            "actor": "ops.legacy",
            "actor_type": "user",
            "changed_at": now,
            "summary": "Legacy CMDB event",
            "content_hash": "sim-sha256:legacy-v1",
            "execution_mode": "SIMULATED",
            "data_source": "SYNTHETIC_DEMO",
            "note": "Synthetic demo event — not a live filesystem change.",
            "tenant_id": MIGRATION_TENANT_ID,
            "created_at": now,
        }
    )
    assert monitor["file_watch_targets"].count_documents(filt) == 0

    listed = client.get("/api/file-monitoring/targets", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    ids = {i["watch_id"] for i in listed.json()["items"]}
    assert "fw-legacy-cmdb" in ids

    # Migrated into monitor; CMDB source retained during dual-read window.
    assert monitor["file_watch_targets"].count_documents(filt) >= 1
    assert monitor["file_version_events"].count_documents(
        {**filt, "event_id": "fve-legacy-cmdb-v1"}
    ) == 1
    assert cmdb["file_watch_targets"].count_documents(
        {**filt, "watch_id": "fw-legacy-cmdb"}
    ) == 1

    detail = client.get(
        "/api/file-monitoring/targets/fw-legacy-cmdb", headers=auth_headers
    )
    assert detail.status_code == 200
    versions = client.get(
        "/api/file-monitoring/targets/fw-legacy-cmdb/versions",
        headers=auth_headers,
    )
    assert versions.status_code == 200
    assert versions.json()["total"] >= 1


def test_cross_tenant_insert_uses_monitor_db(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.db import get_monitor_database
    from app.services import tenants as tenants_service
    from app.tenancy import MIGRATION_TENANT_ID

    tenants_service.ensure_migration_tenant()
    client.get("/api/file-monitoring/targets", headers=auth_headers)

    other_id = "tenant-fm-other"
    now = datetime.now(timezone.utc)
    from app.db import get_database

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
