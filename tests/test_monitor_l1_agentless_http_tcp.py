"""Monitoring L1 — agentless check CRUD + HTTP/TCP poller + egress (0.89.0)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import Settings, get_settings
from app.db import require_monitor_database
from app.monitor.services import egress as egress_service
from app.monitor.services import poller as poller_service
from app.monitor.services.egress import EgressDenied, assert_egress_allowed
from app.services import entitlements as entitlements_service
from app.services import tenants as tenants_service
from app.tenancy import MIGRATION_TENANT_ID
from tests.frontend_paths import FRONTEND_INDEX


@pytest.fixture()
def live_platform_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "false")
    monkeypatch.setenv("MONITOR_POLLER_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def live_platform_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_AGENTLESS_ENABLED", "true")
    monkeypatch.setenv("MONITOR_POLLER_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def live_with_allowlist(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_AGENTLESS_ENABLED", "true")
    monkeypatch.setenv("MONITOR_EGRESS_ALLOWLIST", "example.com,127.0.0.1,::1")
    monkeypatch.setenv("MONITOR_POLLER_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _opt_in_agentless(client: TestClient, auth_headers: dict[str, str]) -> None:
    tenants_service.ensure_migration_tenant()
    resp = client.patch(
        "/api/monitor/admin/live-settings",
        headers=auth_headers,
        json={
            "monitor_live_opt_in": True,
            "monitor_live_agentless_opt_in": True,
        },
    )
    assert resp.status_code == 200, resp.text


def _create_http_check(
    client: TestClient, auth_headers: dict[str, str], *, url: str = "http://example.com/"
) -> dict:
    resp = client.post(
        "/api/monitor/checks",
        headers=auth_headers,
        json={
            "target_id": "tgt-demo-1",
            "component_id": "cmp-demo-1",
            "protocol": "http",
            "endpoint": {"url": url, "method": "GET", "expect_status": 200},
            "interval_seconds": 60,
            "timeout_seconds": 2,
            "enabled": True,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_version_bump_for_monitor_l1() -> None:
    assert __version__ == "0.89.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.89.0"' in html
    assert "monitor/index.js?v=0.89.0" in html


def test_monitor_live_checks_entitlement_in_catalog() -> None:
    starter = entitlements_service.get_plan("starter")
    standard = entitlements_service.get_plan("standard")
    unlimited = entitlements_service.get_plan("legacy_unlimited")
    assert starter["limits"]["monitor_live_checks"] == 20
    assert standard["limits"]["monitor_live_checks"] == 200
    assert unlimited["limits"]["monitor_live_checks"] is None


def test_checks_crud_tenant_scoped(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    """CRUD works without live gates (definitions only)."""
    tenants_service.ensure_migration_tenant()
    created = _create_http_check(client, auth_headers)
    check_id = created["check_id"]
    assert created["protocol"] == "http"
    assert created["collect_mode"] == "AGENTLESS"
    assert created["tenant_id"] == MIGRATION_TENANT_ID

    listed = client.get("/api/monitor/checks", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] >= 1
    assert any(i["check_id"] == check_id for i in listed.json()["items"])

    got = client.get(f"/api/monitor/checks/{check_id}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["check_id"] == check_id

    patched = client.patch(
        f"/api/monitor/checks/{check_id}",
        headers=auth_headers,
        json={"enabled": False, "interval_seconds": 120},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["enabled"] is False
    assert patched.json()["interval_seconds"] == 120

    deleted = client.delete(f"/api/monitor/checks/{check_id}", headers=auth_headers)
    assert deleted.status_code == 204, deleted.text
    assert (
        client.get(f"/api/monitor/checks/{check_id}", headers=auth_headers).status_code
        == 404
    )


def test_icmp_accepted_as_l2_protocol(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    """L2 unlocked icmp/snmp; L1 suite still covers HTTP/TCP paths."""
    tenants_service.ensure_migration_tenant()
    resp = client.post(
        "/api/monitor/checks",
        headers=auth_headers,
        json={
            "target_id": "tgt-1",
            "protocol": "icmp",
            "endpoint": {"host": "example.com"},
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["protocol"] == "icmp"


def test_run_once_403_when_gates_off(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    created = _create_http_check(client, auth_headers)
    resp = client.post(
        f"/api/monitor/checks/{created['check_id']}/run-once",
        headers=auth_headers,
    )
    assert resp.status_code == 403, resp.text


def test_egress_empty_allowlist_denies() -> None:
    with pytest.raises(EgressDenied) as exc:
        assert_egress_allowed(
            hostname="example.com",
            platform_allowlist="",
            resolve=False,
        )
    assert "empty" in exc.value.message.lower() or "deny" in exc.value.message.lower()


def test_egress_ssrf_metadata_denied_unless_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Hostname allowlisted, but DNS returns metadata IP → deny.
    monkeypatch.setattr(
        egress_service,
        "_resolve_ips",
        lambda hostname: ["169.254.169.254"],
    )
    with pytest.raises(EgressDenied) as exc:
        assert_egress_allowed(
            hostname="looks-safe.example",
            platform_allowlist="looks-safe.example",
            resolve=True,
        )
    assert "sensitive" in exc.value.message.lower()

    # Explicit IP allowlist entry permits lab use.
    monkeypatch.setattr(
        egress_service,
        "_resolve_ips",
        lambda hostname: ["169.254.169.254"],
    )
    ips = assert_egress_allowed(
        hostname="looks-safe.example",
        platform_allowlist="looks-safe.example,169.254.169.254",
        resolve=True,
    )
    assert "169.254.169.254" in ips


def test_egress_host_not_in_allowlist() -> None:
    with pytest.raises(EgressDenied) as exc:
        assert_egress_allowed(
            hostname="evil.example",
            platform_allowlist="example.com",
            resolve=False,
        )
    assert "not in platform" in exc.value.message


def test_run_once_allowlist_denial_no_live_write(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty/mismatched allowlist → denied; no LIVE samples/results written."""
    monkeypatch.setenv("MONITOR_EGRESS_ALLOWLIST", "")
    get_settings.cache_clear()
    _opt_in_agentless(client, auth_headers)
    created = _create_http_check(client, auth_headers)
    check_id = created["check_id"]
    resp = client.post(
        f"/api/monitor/checks/{check_id}/run-once", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["denied"] is True
    assert body["live_written"] is False
    assert body["result"] is None
    assert body["sample"] is None

    db = require_monitor_database()
    assert db["monitor_check_results"].count_documents({"check_id": check_id}) == 0
    assert db["metric_samples"].count_documents(
        {"check_id": check_id, "execution_mode": "LIVE"}
    ) == 0


def test_run_once_http_writes_live_sample(
    live_with_allowlist,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_agentless(client, auth_headers)
    created = _create_http_check(client, auth_headers)
    check_id = created["check_id"]

    fake_outcome = {
        "ok": True,
        "latency_ms": 12.5,
        "value": 200.0,
        "message": "HTTP 200",
        "denied": False,
    }
    with patch(
        "app.monitor.services.executors.execute_http_check",
        return_value=fake_outcome,
    ):
        resp = client.post(
            f"/api/monitor/checks/{check_id}/run-once", headers=auth_headers
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["live_written"] is True
    assert body["execution_mode"] == "LIVE"
    assert body["result"]["execution_mode"] == "LIVE"
    assert body["sample"]["execution_mode"] == "LIVE"
    assert body["sample"]["data_source"] == "HTTP_CHECK"

    results = client.get(
        f"/api/monitor/checks/{check_id}/results", headers=auth_headers
    )
    assert results.status_code == 200, results.text
    assert results.json()["total"] >= 1


def test_run_once_tcp_writes_live_sample(
    live_with_allowlist,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_agentless(client, auth_headers)
    created = client.post(
        "/api/monitor/checks",
        headers=auth_headers,
        json={
            "target_id": "tgt-tcp-1",
            "protocol": "tcp",
            "endpoint": {"host": "example.com", "port": 443},
            "timeout_seconds": 2,
        },
    )
    assert created.status_code == 201, created.text
    check_id = created.json()["check_id"]
    fake_outcome = {
        "ok": True,
        "latency_ms": 8.0,
        "value": 8.0,
        "message": "tcp connect ok",
        "denied": False,
    }
    with patch(
        "app.monitor.services.executors.execute_tcp_check",
        return_value=fake_outcome,
    ):
        resp = client.post(
            f"/api/monitor/checks/{check_id}/run-once", headers=auth_headers
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["live_written"] is True
    assert resp.json()["sample"]["data_source"] == "TCP_CHECK"


def test_poller_noop_when_disabled(
    live_platform_off,
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    result = poller_service.run_tick(force=False)
    assert result["skipped"] is True
    assert result["ran"] == 0
    assert poller_service.start_poller() is False


def test_poller_tick_admin_respects_gates(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_agentless(client, auth_headers)
    resp = client.post("/api/monitor/admin/poller/tick", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True


def test_entitlement_blocks_check_create(
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenants_service.ensure_migration_tenant()
    monkeypatch.setattr(
        entitlements_service,
        "monitor_live_checks_limit",
        lambda tenant_id: 0,
    )
    resp = client.post(
        "/api/monitor/checks",
        headers=auth_headers,
        json={
            "target_id": "tgt-1",
            "protocol": "http",
            "endpoint": {"url": "http://example.com/"},
        },
    )
    assert resp.status_code == 403, resp.text


def test_meta_exposes_checks_paths(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    body = client.get("/api/monitor/meta", headers=auth_headers).json()
    assert body["checks"] == "/api/monitor/checks"
    assert body["poller_tick"] == "/api/monitor/admin/poller/tick"


def test_indexes_include_checks(clean_db) -> None:
    from app.monitor.services.indexes import ensure_monitor_indexes

    result = ensure_monitor_indexes()
    assert "monitor_checks" in result["indexes"]
    assert "monitor_check_results" in result["indexes"]


def test_platform_poller_default_false() -> None:
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert settings.monitor_poller_enabled is False
    assert (settings.monitor_egress_allowlist or "") == ""
    get_settings.cache_clear()
