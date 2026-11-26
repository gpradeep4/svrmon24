"""Monitoring L10 — live hardening: indexes, fail-closed matrix, egress, isolation (0.99.9)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import get_settings
from app.db import get_monitor_database, require_monitor_database
from app.monitor.services.indexes import ensure_monitor_indexes
from app.monitor.services.meta import FAIL_CLOSED_MATRIX
from app.services import entitlements as entitlements_service
from app.services import tenants as tenants_service
from app.tenancy import MIGRATION_TENANT_ID, stamp_tenant_id, tenant_filter
from tests.frontend_paths import FRONTEND_DIR, FRONTEND_INDEX


@pytest.fixture()
def live_platform_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "false")
    monkeypatch.setenv("MONITOR_EGRESS_ALLOWLIST", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def live_platform_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_AGENTLESS_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_HTTP_INGEST_ENABLED", "true")
    monkeypatch.setenv("MONITOR_EGRESS_ALLOWLIST", "example.com,127.0.0.1")
    monkeypatch.setenv("MONITOR_AGENT_TOKEN_PEPPER", "test-pepper-l10")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_version_bump_for_monitor_l10() -> None:
    assert __version__ == "0.99.9"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.9"' in html
    assert "monitor/dashboard.js?v=0.99.9" in html
    assert 'id="monitorLiveGateChips"' in html
    assert 'data-monitor-live-chips="1"' in html
    assert "monitorDashEgress" in html
    assert "Data is SIMULATED — no live probes" not in html
    assert "does not run live probes or agents" not in html

    dash_js = Path("frontend/static/js/monitor/dashboard.js").read_text(encoding="utf-8")
    assert "renderLiveGateChips" in dash_js
    assert "monitorLiveGateChips" in dash_js
    assert "fail-closed" in dash_js.lower() or "gates" in dash_js

    css = Path("frontend/static/css/monitor.css").read_text(encoding="utf-8")
    assert "monitor-gate-chip" in css


def test_meta_fail_closed_matrix_and_egress(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    response = client.get("/api/monitor/meta", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["live_probes"] is False
    assert body["live_path_complete"] is True
    assert body["live_slices"] == [
        "L0",
        "L1",
        "L2",
        "L3",
        "L4",
        "L5",
        "L6",
        "L7",
        "L8",
        "L9",
        "L10",
    ]
    matrix = body["fail_closed_matrix"]
    assert set(matrix.keys()) >= set(FAIL_CLOSED_MATRIX.keys())
    assert "agentless_poll" in matrix
    assert "auto_incident" in matrix
    assert "requires" in matrix["agentless_poll"]
    assert "when_off" in matrix["agentless_poll"]

    egress = body["egress"]
    assert egress["env_var"] == "MONITOR_EGRESS_ALLOWLIST"
    assert egress["deny_all_when_empty"] is True
    assert egress["configured"] is False
    assert "entries" not in egress  # public meta omits host list
    assert body["egress_admin"] == "/api/monitor/admin/egress"
    assert "live_never_copy" in (body.get("deprecations") or {})
    assert "fail-closed" in body["banner"].lower() or "gates" in body["banner"].lower()
    assert "fail_closed_matrix" in body["notice"]


def test_admin_egress_and_live_settings_surface(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    egress = client.get("/api/monitor/admin/egress", headers=auth_headers)
    assert egress.status_code == 200, egress.text
    body = egress.json()
    assert body["configured"] is True
    assert body["entry_count"] >= 2
    assert "example.com" in body["entries"]
    assert body["deny_all_when_empty"] is True

    settings = client.get("/api/monitor/admin/live-settings", headers=auth_headers)
    assert settings.status_code == 200, settings.text
    payload = settings.json()
    assert "egress" in payload
    assert payload["egress"]["configured"] is True
    assert payload["platform"].get("monitor_egress_allowlist")


def test_monitor_indexes_include_execution_mode(clean_db) -> None:
    result = ensure_monitor_indexes()
    assert result["ok"] is True
    samples = result["indexes"]["metric_samples"]
    assert any("execution_mode" in str(x) for x in samples)
    logs = result["indexes"]["log_events"]
    assert any("execution_mode" in str(x) for x in logs)
    files = result["indexes"]["file_version_events"]
    assert any("execution_mode" in str(x) for x in files)
    checks = result["indexes"]["monitor_check_results"]
    assert any("execution_mode" in str(x) for x in checks)
    targets = result["indexes"]["monitor_targets"]
    assert any("execution_mode" in str(x) for x in targets)


def test_live_ingest_isolation_between_tenants(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    """LIVE log rows for tenant A must not appear under tenant B queries."""
    tenants_service.ensure_migration_tenant()
    tenant_a = MIGRATION_TENANT_ID
    tenant_b = "tenant-foreign-l10"
    opt = client.patch(
        "/api/monitor/admin/live-settings",
        headers=auth_headers,
        json={
            "monitor_live_opt_in": True,
            "monitor_live_agentless_opt_in": True,
        },
    )
    assert opt.status_code == 200, opt.text

    streams = client.get("/api/monitor/logs/streams", headers=auth_headers)
    assert streams.status_code == 200, streams.text
    stream_id = streams.json()["items"][0]["stream_id"]

    ingest = client.post(
        "/api/monitor/ingest/logs",
        headers=auth_headers,
        json={
            "stream_id": stream_id,
            "events": [
                {
                    "message": "l10-iso-live-event",
                    "severity": "warning",
                }
            ],
        },
    )
    assert ingest.status_code == 200, ingest.text
    assert ingest.json()["ok"] is True
    assert ingest.json()["execution_mode"] == "LIVE"
    assert ingest.json()["accepted"] == 1

    db = require_monitor_database()
    live_a = list(
        db["log_events"].find(
            {
                **tenant_filter(tenant_a),
                "execution_mode": "LIVE",
                "message": "l10-iso-live-event",
            }
        )
    )
    assert len(live_a) >= 1

    # Foreign tenant filter must not see A's LIVE rows.
    assert (
        db["log_events"].count_documents(
            {
                **tenant_filter(tenant_b),
                "execution_mode": "LIVE",
                "message": "l10-iso-live-event",
            }
        )
        == 0
    )
    foreign = list(
        db["log_events"].find(
            {"message": "l10-iso-live-event", "tenant_id": {"$ne": tenant_a}}
        )
    )
    assert foreign == []

    listed = client.get(
        "/api/monitor/logs/events?q=l10-iso-live-event",
        headers=auth_headers,
    )
    assert listed.status_code == 200, listed.text
    items = listed.json().get("items") or []
    assert any(
        row.get("message") == "l10-iso-live-event"
        and row.get("execution_mode") == "LIVE"
        for row in items
    )


def test_retention_sweep_isolation_live_and_simulated(
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant sweep trims own LIVE+SIMULATED rows; foreign tenant untouched."""
    tenants_service.ensure_migration_tenant()
    tenant_a = MIGRATION_TENANT_ID
    tenant_b = "tenant-foreign-l10-ret"
    monkeypatch.setattr(
        entitlements_service, "metric_samples_retained_limit", lambda _tid: 2
    )
    monkeypatch.setattr(
        entitlements_service, "effective_monitor_retention_days", lambda _tid: None
    )

    coll = get_monitor_database()["metric_samples"]
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    for i in range(5):
        for tid, prefix, mode in (
            (tenant_a, "a", "LIVE" if i % 2 else "SIMULATED"),
            (tenant_b, "b", "LIVE"),
        ):
            coll.insert_one(
                stamp_tenant_id(
                    {
                        "sample_id": f"ms-l10-{prefix}-{i}",
                        "target_id": f"mt-{prefix}",
                        "component_id": f"srv-{prefix}",
                        "metric_name": "cpu_pct",
                        "value": float(i),
                        "unit": "%",
                        "observed_at": base + timedelta(minutes=i),
                        "data_source": "HTTP_CHECK" if mode == "LIVE" else "SYNTHETIC_DEMO",
                        "collect_mode": "AGENTLESS",
                        "execution_mode": mode,
                    },
                    tenant_id=tid,
                )
            )

    sweep = client.post(
        "/api/monitor/admin/retention-sweep", headers=auth_headers
    )
    assert sweep.status_code == 200, sweep.text
    assert coll.count_documents(tenant_filter(tenant_a)) == 2
    assert coll.count_documents(tenant_filter(tenant_b)) == 5
    remaining_modes = {
        doc["execution_mode"]
        for doc in coll.find(tenant_filter(tenant_a), {"execution_mode": 1})
    }
    assert remaining_modes  # still has rows after trim
    coll.delete_many(tenant_filter(tenant_b))


def test_fail_closed_matrix_live_stub(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    tenants_service.set_monitor_live_settings(
        MIGRATION_TENANT_ID, {"monitor_live_opt_in": True}
    )
    resp = client.post("/api/monitor/live/probe-stub", headers=auth_headers)
    assert resp.status_code == 403, resp.text

    ingest = client.post(
        "/api/monitor/ingest/logs",
        headers=auth_headers,
        json={"events": [{"message": "blocked", "severity": "info"}]},
    )
    assert ingest.status_code == 403, ingest.text


def test_simulated_deploy_meta_still_m8_compatible(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    """Flags off → M8-era SIMULATED behaviors remain."""
    tenants_service.ensure_migration_tenant()
    meta = client.get("/api/monitor/meta", headers=auth_headers)
    assert meta.status_code == 200
    body = meta.json()
    assert body["live_probes"] is False
    assert body["execution_mode"] == "SIMULATED"
    assert body["entry_path"] == "/monitor"
    assert body["retention_sweep"] == "/api/monitor/admin/retention-sweep"
    deps = body.get("deprecations") or {}
    assert "cmdb_file_monitoring_nav" in deps
    assert "api_diagnostics" in deps

    dash = client.get("/api/monitor/dashboard", headers=auth_headers)
    assert dash.status_code == 200, dash.text
    assert dash.json()["live_probes"] is False
    assert "SIMULATED" in dash.json()["banner"] or "fail-closed" in dash.json()[
        "banner"
    ].lower()


def test_monitor_entry_live_chips_and_fe_be_smoke(
    client: TestClient,
) -> None:
    for path in ("/monitor", "/monitor/"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert b'id="monitorLiveGateChips"' in resp.content
        assert b'id="tab-monitor-dashboard"' in resp.content
        assert b'data-tab="monitor-middleware"' in resp.content

    conf = (FRONTEND_DIR / "nginx.conf").read_text(encoding="utf-8")
    assert "location = /monitor" in conf

    assert Path("app/monitor/services/egress.py").is_file()
    assert Path("app/monitor/services/meta.py").is_file()
    assert Path("app/monitor/routers/admin.py").is_file()
    assert Path("frontend/static/js/monitor/dashboard.js").is_file()


def test_api_only_mode_hides_monitor_html() -> None:
    os.environ["SERVE_STATIC"] = "false"
    from app.config import get_settings as gs
    from app.db import reset_client_for_tests
    from app.main import create_app
    from app.oidc import clear_discovery_cache

    gs.cache_clear()
    clear_discovery_cache()
    reset_client_for_tests()
    try:
        app = create_app()
        with TestClient(app) as client:
            assert client.get("/").status_code == 404
            assert client.get("/monitor").status_code == 404
            # API still available when static is off.
            # Unauthenticated meta may 401 — ensure route exists via OpenAPI or 401/403.
            status = client.get("/api/status")
            assert status.status_code in (200, 401, 403)
    finally:
        os.environ.pop("SERVE_STATIC", None)
        reset_client_for_tests()
        gs.cache_clear()
        clear_discovery_cache()
