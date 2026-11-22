"""Monitoring M0 — DB config, handle, ping field, meta endpoint (0.64.0)."""

from __future__ import annotations

from app import __version__
from app.config import Settings, get_settings
from app.db import (
    get_database,
    get_itsm_database,
    get_monitor_database,
    ping_database,
    reset_client_for_tests,
)
from fastapi.testclient import TestClient


def test_version_bump_for_monitor_m0() -> None:
    assert __version__ == "0.78.0"


def test_monitor_default_database_is_svrmon_monitor(monkeypatch) -> None:
    monkeypatch.delenv("MONGODB_DB", raising=False)
    monkeypatch.delenv("MONGODB_CMDB_DB", raising=False)
    monkeypatch.delenv("MONGODB_ITSM_DB", raising=False)
    monkeypatch.delenv("MONGODB_MONITOR_DB", raising=False)
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert settings.mongodb_monitor_db == "svrmon-monitor"
    assert settings.monitor_database_name == "svrmon-monitor"
    assert settings.cmdb_database_name == "svrmon-cmdb"
    assert settings.itsm_database_name == "svrmon-itsm"
    get_settings.cache_clear()


def test_monitor_blank_env_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("MONGODB_MONITOR_DB", "   ")
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert settings.monitor_database_name == "svrmon-monitor"
    get_settings.cache_clear()


def test_get_monitor_database_uses_resolved_name(monkeypatch) -> None:
    monkeypatch.setenv("MONGODB_CMDB_DB", "explicit-cmdb-handle")
    monkeypatch.setenv("MONGODB_ITSM_DB", "explicit-itsm-handle")
    monkeypatch.setenv("MONGODB_MONITOR_DB", "explicit-monitor-handle")
    get_settings.cache_clear()
    reset_client_for_tests()
    settings = Settings(_env_file=None)
    assert get_database(settings).name == "explicit-cmdb-handle"
    assert get_itsm_database(settings).name == "explicit-itsm-handle"
    assert get_monitor_database(settings).name == "explicit-monitor-handle"
    assert get_monitor_database(settings).name != get_database(settings).name
    assert get_monitor_database(settings).name != get_itsm_database(settings).name
    reset_client_for_tests()
    get_settings.cache_clear()


def test_ping_reports_monitor_database(monkeypatch) -> None:
    monkeypatch.setenv("MONGODB_DB", "svrmon-cmdb-ping-probe")
    monkeypatch.delenv("MONGODB_CMDB_DB", raising=False)
    monkeypatch.setenv("MONGODB_ITSM_DB", "svrmon-itsm-ping-probe")
    monkeypatch.setenv("MONGODB_MONITOR_DB", "svrmon-monitor-ping-probe")
    get_settings.cache_clear()
    reset_client_for_tests()
    settings = Settings(_env_file=None)
    status = ping_database(settings)
    assert status["cmdb_database"] == "svrmon-cmdb-ping-probe"
    assert status["itsm_database"] == "svrmon-itsm-ping-probe"
    assert status["monitor_database"] == "svrmon-monitor-ping-probe"
    reset_client_for_tests()
    get_settings.cache_clear()


def test_api_status_exposes_monitor_database(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/status", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    mongo = payload.get("mongodb") or {}
    assert "monitor_database" in mongo
    assert mongo["monitor_database"] != mongo["cmdb_database"]
    assert mongo["monitor_database"] != mongo["itsm_database"]
    assert payload.get("version") == "0.78.0"


def test_monitor_meta_requires_auth(client: TestClient) -> None:
    response = client.get("/api/monitor/meta")
    assert response.status_code in {401, 403}


def test_monitor_meta_simulated_tenant_aware(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/monitor/meta", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["module"] == "monitoring"
    assert body["execution_mode"] == "SIMULATED"
    assert body["live_probes"] is False
    assert body["demo_only"] is True
    assert body["collect_modes"] == ["agentless", "agent"]
    assert "server" in body["domains"]
    assert "linux" in body["os_families"]
    assert "windows" in body["os_families"]
    assert "macos" in body["os_families"]
    assert "unix" in body["os_families"]
    assert "switch" in body["network_target_kinds"]
    assert "firewall" in body["network_target_kinds"]
    assert "SIMULATED" in body["banner"]
    assert body["monitor_database"]
    assert body["database"] == body["monitor_database"]
    assert body["tenant_id"]
    assert "svrmon" in body["monitor_database"] or "monitor" in body["monitor_database"]
