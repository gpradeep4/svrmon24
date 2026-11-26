"""Monitoring L0 — live gates, meta, model widenings, fail-closed stubs.

Version assertion tracks current package (L2 bumped to 0.99.6).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import Settings, get_settings
from app.db import get_database
from app.monitor.models.literals import DATA_SOURCES, DOMAINS, EXECUTION_MODES
from app.monitor.models.targets import DataSource, Domain, ExecutionMode, MonitorTarget
from app.services import tenants as tenants_service
from app.tenancy import MIGRATION_TENANT_ID
from tests.frontend_paths import FRONTEND_INDEX


@pytest.fixture()
def live_platform_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def live_platform_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_version_bump_for_monitor_l0() -> None:
    assert __version__ == "0.99.6"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.6"' in html
    assert "monitor/index.js?v=0.99.6" in html


def test_platform_flag_defaults_false() -> None:
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert settings.monitor_live_probes_enabled is False
    assert settings.monitor_live_agentless_enabled is True
    assert settings.monitor_live_agent_enabled is True
    assert settings.monitor_poller_enabled is False
    assert (settings.monitor_live_syslog_bind or "") == ""
    get_settings.cache_clear()


def test_model_widenings_accept_live_literals() -> None:
    assert "LIVE" in EXECUTION_MODES
    assert "SIMULATED" in EXECUTION_MODES
    assert "middleware" in DOMAINS
    assert "HTTP_CHECK" in DATA_SOURCES
    assert "AGENT" in DATA_SOURCES
    # Typing aliases remain importable from targets models.
    _em: ExecutionMode = "LIVE"
    _ds: DataSource = "HTTP_CHECK"
    _dom: Domain = "middleware"
    assert _em == "LIVE"
    assert _ds == "HTTP_CHECK"
    assert _dom == "middleware"
    target = MonitorTarget(
        target_id="t1",
        component_id="c1",
        domain="middleware",
        collect_mode="AGENTLESS",
        execution_mode="LIVE",
        data_source="HTTP_CHECK",
    )
    assert target.execution_mode == "LIVE"
    assert target.domain == "middleware"


def test_meta_defaults_live_probes_false(
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
    assert body["execution_mode"] == "SIMULATED"
    assert body["execution_modes"] == ["SIMULATED", "LIVE"]
    assert body["demo_only"] is True
    assert "middleware" in body["domains"]
    gates = body["live_gates"]
    assert gates["platform_enabled"] is False
    assert gates["tenant_opt_in"] is False
    assert gates["agentless"] is False
    assert gates["agent"] is False
    assert gates["auto_incident"] is False
    assert body["retention_tier"] == "hot"
    assert "SIMULATED" in body["banner"]
    assert body["live_settings"] == "/api/monitor/admin/live-settings"
    assert body["live_probe_stub"] == "/api/monitor/live/probe-stub"


def test_probe_stub_403_when_platform_off(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    # Even with tenant opt-in, platform off → 403.
    tenants_service.set_monitor_live_settings(
        MIGRATION_TENANT_ID, {"monitor_live_opt_in": True}
    )
    resp = client.post("/api/monitor/live/probe-stub", headers=auth_headers)
    assert resp.status_code == 403, resp.text
    payload = resp.json()
    message = str(
        payload.get("detail")
        or (payload.get("error") or {}).get("message")
        or payload
    ).lower()
    assert "disabled" in message


def test_probe_stub_403_when_tenant_off(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    resp = client.post("/api/monitor/live/probe-stub", headers=auth_headers)
    assert resp.status_code == 403, resp.text


def test_probe_stub_200_when_both_on(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    patched = client.patch(
        "/api/monitor/admin/live-settings",
        headers=auth_headers,
        json={
            "monitor_live_opt_in": True,
            "monitor_live_agentless_opt_in": True,
            "monitor_live_agent_opt_in": True,
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["live_probes"] is True
    assert patched.json()["tenant"]["monitor_live_opt_in"] is True

    meta = client.get("/api/monitor/meta", headers=auth_headers)
    assert meta.status_code == 200
    assert meta.json()["live_probes"] is True
    assert meta.json()["live_gates"]["platform_enabled"] is True
    assert meta.json()["live_gates"]["tenant_opt_in"] is True

    stub = client.post("/api/monitor/live/probe-stub", headers=auth_headers)
    assert stub.status_code == 200, stub.text
    body = stub.json()
    assert body["ok"] is True
    assert body["stub"] is True
    assert body["execution_mode"] == "LIVE"


def test_ingest_and_poll_stubs_fail_closed(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    for path in (
        "/api/monitor/ingest/logs",
        "/api/monitor/ingest/metrics",
        "/api/monitor/ingest/file-events",
        "/api/monitor/checks/chk-demo/run-once",
    ):
        resp = client.post(path, headers=auth_headers)
        assert resp.status_code == 403, path


def test_ingest_stubs_open_when_capability_gates_on(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    assert (
        client.patch(
            "/api/monitor/admin/live-settings",
            headers=auth_headers,
            json={
                "monitor_live_opt_in": True,
                "monitor_live_agentless_opt_in": True,
                "monitor_live_agent_opt_in": True,
            },
        ).status_code
        == 200
    )
    logs = client.post("/api/monitor/ingest/logs", headers=auth_headers)
    assert logs.status_code == 200, logs.text
    assert logs.json()["execution_mode"] == "LIVE"
    metrics = client.post("/api/monitor/ingest/metrics", headers=auth_headers)
    assert metrics.status_code == 200, metrics.text
    # L1: run-once is real — missing check → 404 (gate open), not 403.
    missing = client.post("/api/monitor/checks/chk-1/run-once", headers=auth_headers)
    assert missing.status_code == 404, missing.text


def test_live_settings_audit_on_toggle(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    resp = client.patch(
        "/api/monitor/admin/live-settings",
        headers=auth_headers,
        json={"monitor_live_opt_in": True},
    )
    assert resp.status_code == 200, resp.text
    events = list(
        get_database()["audit_events"].find(
            {
                "tenant_id": MIGRATION_TENANT_ID,
                "action": "monitor.live_settings.update",
            }
        )
    )
    assert len(events) >= 1
    assert events[-1]["details"].get("monitor_live_opt_in") is True


def test_simulated_meta_unchanged_shape_when_live_off(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    """SIMULATED path contract remains for default deploys."""
    tenants_service.ensure_migration_tenant()
    body = client.get("/api/monitor/meta", headers=auth_headers).json()
    assert body["module"] == "monitoring"
    assert body["live_probes"] is False
    assert body["collect_modes"] == ["agentless", "agent"]
    assert "server" in body["domains"]
    assert body["entry_path"] == "/monitor"
