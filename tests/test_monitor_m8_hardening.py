"""Monitoring M8 — hardening: indexes, retention, diagnostics rehome, /monitor (0.86.0)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import __version__
from app.db import get_database, get_monitor_database, require_monitor_database
from app.monitor.services import diagnostics as monitor_diagnostics
from app.monitor.services.indexes import ensure_monitor_indexes
from app.tenancy import MIGRATION_TENANT_ID, stamp_tenant_id, tenant_filter
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_DIR, FRONTEND_INDEX


def test_version_bump_for_monitor_m8() -> None:
    assert __version__ == "0.86.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.86.0"' in html
    assert "monitor/index.js?v=0.86.0" in html


def test_cmdb_redirect_stubs_removed() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert "cmdb-redirect-file-monitoring" not in html
    assert "cmdb-redirect-diagnostics" not in html
    assert "data-cmdb-monitor-redirect" not in html
    cmdb = Path("frontend/static/js/cmdb.js").read_text(encoding="utf-8")
    assert "cmdb-redirect-file-monitoring" not in cmdb
    mon = Path("frontend/static/js/monitor/index.js").read_text(encoding="utf-8")
    assert "data-cmdb-monitor-redirect" not in mon


def test_monitor_entry_route_and_nginx(client: TestClient) -> None:
    root = client.get("/")
    assert root.status_code == 200
    for path in ("/monitor", "/monitor/"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert "text/html" in resp.headers.get("content-type", "")
        assert b"svrmon24-version" in resp.content
        assert b'id="tab-monitor-dashboard"' in resp.content

    conf = (FRONTEND_DIR / "nginx.conf").read_text(encoding="utf-8")
    assert "location = /monitor" in conf
    assert "location = /monitor/" in conf

    routing = Path("frontend/static/js/itsm/routing.js").read_text(encoding="utf-8")
    assert "isMonitorEntryPath" in routing
    assert "monitor-dashboard" in routing


def test_api_only_mode_hides_monitor_entry_html() -> None:
    os.environ["SERVE_STATIC"] = "false"
    from app.config import get_settings
    from app.db import reset_client_for_tests
    from app.main import create_app
    from app.oidc import clear_discovery_cache

    get_settings.cache_clear()
    clear_discovery_cache()
    reset_client_for_tests()
    try:
        app = create_app()
        with TestClient(app) as client:
            assert client.get("/").status_code == 404
            assert client.get("/monitor").status_code == 404
            assert client.get("/monitor/").status_code == 404
    finally:
        os.environ.pop("SERVE_STATIC", None)
        reset_client_for_tests()
        get_settings.cache_clear()
        clear_discovery_cache()


def test_meta_documents_deprecations_and_entry(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    response = client.get("/api/monitor/meta", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["live_probes"] is False
    assert body["execution_mode"] == "SIMULATED"
    assert body["entry_path"] == "/monitor"
    assert body["retention_sweep"] == "/api/monitor/admin/retention-sweep"
    deps = body.get("deprecations") or {}
    assert "cmdb_file_monitoring_nav" in deps
    assert "cmdb_diagnostics_nav" in deps
    assert "api_diagnostics" in deps
    assert "api_file_monitoring" in deps


def test_monitor_indexes_include_diagnostics(clean_db) -> None:
    result = ensure_monitor_indexes()
    assert result["ok"] is True
    assert "diagnostic_history" in result["collections"]
    indexes = result["indexes"]["diagnostic_history"]
    assert any("tenant_diagnostic_id_unique" in str(x) for x in indexes)


def test_diagnostics_rehome_to_monitor_db(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_id": "srv-m8-diag",
            "component_type": "Server",
            "name": "m8-diag-host",
            "environment": "prod",
            "status": "active",
            "hostname": "m8-diag-host",
            "os_family": "Linux",
            "os_version": "9",
        },
    )
    assert created.status_code == 201, created.text

    run = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={"component_id": "srv-m8-diag", "profile_name": "basic-health"},
    )
    assert run.status_code == 201, run.text
    diag_id = run.json()["diagnostic_id"]

    monitor_db = require_monitor_database()
    cmdb_db = get_database()
    assert (
        monitor_db["diagnostic_history"].count_documents({"diagnostic_id": diag_id})
        == 1
    )
    # New writes land only on monitor DB (CMDB source not updated).
    assert (
        cmdb_db["diagnostic_history"].count_documents({"diagnostic_id": diag_id}) == 0
    )

    listed = client.get("/api/diagnostics", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    from app.config import get_settings

    assert listed.json().get("database") == get_settings().monitor_database_name


def test_diagnostics_dual_read_migrate_from_cmdb(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    tenant_id = MIGRATION_TENANT_ID
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    legacy = stamp_tenant_id(
        {
            "diagnostic_id": "diag-legacy-m8",
            "timestamp": now,
            "created_at": now,
            "execution_mode": "SIMULATED",
            "profile_name": "basic-health",
            "component_id": "srv-legacy",
            "component": {"component_id": "srv-legacy"},
            "dependency_context": {"source": "cmdb_relationships"},
            "checks": [],
            "summary": {"overall_status": "ok", "check_count": 0, "ok_count": 0},
            "labels": {"demo": True, "simulated": True, "real_telemetry": False},
        },
        tenant_id=tenant_id,
    )
    get_database()["diagnostic_history"].insert_one(legacy)

    migrated = monitor_diagnostics.migrate_tenant_from_cmdb(tenant_id=tenant_id)
    assert migrated["migrated"] is True
    assert migrated["diagnostics"] == 1

    again = monitor_diagnostics.migrate_tenant_from_cmdb(tenant_id=tenant_id)
    assert again["migrated"] is False
    assert again["reason"] == "monitor_already_populated"

    got = client.get("/api/diagnostics/diag-legacy-m8", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["diagnostic_id"] == "diag-legacy-m8"


def test_retention_sweep_trims_metric_samples(
    client: TestClient, auth_headers: dict[str, str], clean_db, monkeypatch
) -> None:
    from app.services import entitlements as entitlements_service
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    tenant_id = MIGRATION_TENANT_ID
    monkeypatch.setattr(
        entitlements_service, "metric_samples_retained_limit", lambda _tid: 3
    )

    coll = get_monitor_database()["metric_samples"]
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(8):
        coll.insert_one(
            stamp_tenant_id(
                {
                    "sample_id": f"ms-m8-{i}",
                    "target_id": "mt-m8",
                    "component_id": "srv-m8",
                    "metric_name": "cpu_pct",
                    "value": float(i),
                    "unit": "%",
                    "observed_at": base + timedelta(minutes=i),
                    "data_source": "SYNTHETIC_DEMO",
                    "collect_mode": "AGENTLESS",
                    "execution_mode": "SIMULATED",
                },
                tenant_id=tenant_id,
            )
        )
    sweep = client.post(
        "/api/monitor/admin/retention-sweep", headers=auth_headers
    )
    assert sweep.status_code == 200, sweep.text
    body = sweep.json()
    assert body["metric_samples_trimmed"] >= 5
    assert body["live_probes"] is False
    assert coll.count_documents(tenant_filter(tenant_id)) == 3


def test_retention_sweep_isolation_between_tenants(
    client: TestClient, auth_headers: dict[str, str], clean_db, monkeypatch
) -> None:
    from app.services import entitlements as entitlements_service
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    tenant_a = MIGRATION_TENANT_ID
    tenant_b = "tenant-foreign-m8"
    monkeypatch.setattr(
        entitlements_service, "metric_samples_retained_limit", lambda _tid: 2
    )

    coll = get_monitor_database()["metric_samples"]
    base = datetime(2026, 2, 1, tzinfo=timezone.utc)
    for i in range(5):
        coll.insert_one(
            stamp_tenant_id(
                {
                    "sample_id": f"ms-a-{i}",
                    "target_id": "mt-a",
                    "component_id": "srv-a",
                    "metric_name": "cpu_pct",
                    "value": 1.0,
                    "unit": "%",
                    "observed_at": base + timedelta(minutes=i),
                    "data_source": "SYNTHETIC_DEMO",
                    "collect_mode": "AGENT",
                    "execution_mode": "SIMULATED",
                },
                tenant_id=tenant_a,
            )
        )
        coll.insert_one(
            stamp_tenant_id(
                {
                    "sample_id": f"ms-b-{i}",
                    "target_id": "mt-b",
                    "component_id": "srv-b",
                    "metric_name": "cpu_pct",
                    "value": 2.0,
                    "unit": "%",
                    "observed_at": base + timedelta(minutes=i),
                    "data_source": "SYNTHETIC_DEMO",
                    "collect_mode": "AGENT",
                    "execution_mode": "SIMULATED",
                },
                tenant_id=tenant_b,
            )
        )

    sweep = client.post(
        "/api/monitor/admin/retention-sweep", headers=auth_headers
    )
    assert sweep.status_code == 200, sweep.text
    assert coll.count_documents(tenant_filter(tenant_a)) == 2
    # Foreign tenant untouched by this tenant's sweep.
    assert coll.count_documents(tenant_filter(tenant_b)) == 5
    coll.delete_many(tenant_filter(tenant_b))


def test_fe_be_smoke_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'data-tab="monitor-dashboard"' in html
    assert 'data-tab="file-monitoring"' in html
    assert 'data-tab="diagnostics"' in html
    assert "monitor.css?v=0.86.0" in html
    assert "itsm/routing.js?v=0.86.0" in html
    assert Path("app/monitor/services/retention.py").is_file()
    assert Path("app/monitor/services/diagnostics.py").is_file()
    assert Path("app/monitor/routers/admin.py").is_file()
