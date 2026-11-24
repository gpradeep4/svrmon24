"""Monitoring L3 — LIVE HTTP log ingest + optional syslog (0.98.0)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import Settings, get_settings
from app.db import require_monitor_database
from app.monitor.services import ingest as ingest_service
from app.monitor.services import syslog_receiver
from app.services import entitlements as entitlements_service
from app.services import tenants as tenants_service
from app.tenancy import MIGRATION_TENANT_ID, tenant_filter
from tests.frontend_paths import FRONTEND_INDEX


@pytest.fixture()
def live_platform_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "false")
    monkeypatch.setenv("MONITOR_LIVE_SYSLOG_BIND", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def live_platform_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_HTTP_INGEST_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_AGENTLESS_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_SYSLOG_BIND", "")
    monkeypatch.setenv("MONITOR_AGENT_TOKEN_PEPPER", "test-pepper-l3")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def live_with_syslog_bind(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_HTTP_INGEST_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_AGENTLESS_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_SYSLOG_BIND", "127.0.0.1:5514")
    monkeypatch.setenv("MONITOR_AGENT_TOKEN_PEPPER", "test-pepper-l3")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _opt_in(client: TestClient, auth_headers: dict[str, str]) -> None:
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


def _ensure_stream(client: TestClient, auth_headers: dict[str, str]) -> str:
    listed = client.get("/api/monitor/logs/streams", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert items, "expected default streams"
    return items[0]["stream_id"]


def test_version_bump_for_monitor_l3() -> None:
    assert __version__ == "0.98.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.98.0"' in html
    assert "monitor/logs.js?v=0.98.0" in html


def test_monitor_log_ingest_entitlement_in_catalog() -> None:
    starter = entitlements_service.get_plan("starter")
    standard = entitlements_service.get_plan("standard")
    unlimited = entitlements_service.get_plan("legacy_unlimited")
    assert starter["limits"]["monitor_log_ingest_events_per_day"] == 10_000
    assert standard["limits"]["monitor_log_ingest_events_per_day"] == 500_000
    assert unlimited["limits"]["monitor_log_ingest_events_per_day"] is None


def test_http_ingest_403_when_gates_off(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    resp = client.post(
        "/api/monitor/ingest/logs",
        headers=auth_headers,
        json={
            "events": [{"message": "should fail", "severity": "info"}],
        },
    )
    assert resp.status_code == 403, resp.text


def test_http_ingest_writes_live_events(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in(client, auth_headers)
    stream_id = _ensure_stream(client, auth_headers)
    resp = client.post(
        "/api/monitor/ingest/logs",
        headers=auth_headers,
        json={
            "stream_id": stream_id,
            "events": [
                {
                    "severity": "warning",
                    "message": "L3 live ingest probe latency_ms=42",
                    "attrs": {"probe": True},
                }
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["execution_mode"] == "LIVE"
    assert body["data_source"] == "HTTP_INGEST"
    assert body["accepted"] == 1
    assert body["tenant_id"] == MIGRATION_TENANT_ID

    events = client.get(
        f"/api/monitor/logs/events?stream_id={stream_id}&q=L3%20live%20ingest",
        headers=auth_headers,
    )
    assert events.status_code == 200, events.text
    items = events.json()["items"]
    assert len(items) >= 1
    hit = next(i for i in items if "L3 live ingest" in i["message"])
    assert hit["execution_mode"] == "LIVE"
    assert hit["data_source"] == "HTTP_INGEST"
    assert hit["tenant_id"] == MIGRATION_TENANT_ID


def test_ingest_key_auth_and_revoke(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in(client, auth_headers)
    stream_id = _ensure_stream(client, auth_headers)
    created = client.post(
        "/api/monitor/logs/ingest-keys",
        headers=auth_headers,
        json={"name": "collector-a", "stream_id": stream_id},
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    key_id = created.json()["key_id"]
    assert token.startswith("mik_")
    assert "key_hash" not in created.json()

    # Key auth (no Basic) writes LIVE events into the bound stream.
    ingest = client.post(
        "/api/monitor/ingest/logs",
        headers={"X-Monitor-Ingest-Key": token},
        json={
            "events": [
                {"message": "from-ingest-key", "severity": "info"},
            ]
        },
    )
    assert ingest.status_code == 200, ingest.text
    assert ingest.json()["accepted"] == 1

    revoked = client.post(
        f"/api/monitor/logs/ingest-keys/{key_id}/revoke",
        headers=auth_headers,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"

    denied = client.post(
        "/api/monitor/ingest/logs",
        headers={"X-Monitor-Ingest-Key": token},
        json={"events": [{"message": "after-revoke", "severity": "info"}]},
    )
    assert denied.status_code == 401, denied.text


def test_tenant_isolation_on_ingest(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in(client, auth_headers)
    stream_id = _ensure_stream(client, auth_headers)
    resp = client.post(
        "/api/monitor/ingest/logs",
        headers=auth_headers,
        json={
            "stream_id": stream_id,
            "events": [{"message": "iso-check", "severity": "error"}],
        },
    )
    assert resp.status_code == 200, resp.text
    db = require_monitor_database()
    foreign = list(
        db["log_events"].find(
            {"message": "iso-check", "tenant_id": {"$ne": MIGRATION_TENANT_ID}}
        )
    )
    assert foreign == []
    rows = list(
        db["log_events"].find(
            {**tenant_filter(MIGRATION_TENANT_ID), "message": "iso-check"}
        )
    )
    assert rows
    assert all(r["tenant_id"] == MIGRATION_TENANT_ID for r in rows)
    assert all(r["execution_mode"] == "LIVE" for r in rows)


def test_syslog_unbound_by_default() -> None:
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert (settings.monitor_live_syslog_bind or "") == ""
    assert syslog_receiver.parse_bind("") is None
    get_settings.cache_clear()


def test_syslog_known_source_maps_unknown_dropped(
    live_with_syslog_bind,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in(client, auth_headers)
    stream_id = _ensure_stream(client, auth_headers)
    put = client.put(
        "/api/monitor/logs/syslog-sources",
        headers=auth_headers,
        json={
            "sources": [
                {
                    "source_ip": "10.9.8.7",
                    "stream_id": stream_id,
                    "status": "active",
                    "label": "lab-firewall",
                }
            ]
        },
    )
    assert put.status_code == 200, put.text
    assert put.json()["total"] == 1

    # Unknown source → dropped.
    dropped = syslog_receiver.handle_datagram(
        b"<14>unknown host noise",
        ("1.2.3.4", 514),
        settings=get_settings(),
    )
    assert dropped.get("dropped") is True
    assert dropped.get("reason") == "unknown_source"

    # Known source → LIVE SYSLOG event.
    accepted = syslog_receiver.handle_datagram(
        b"<11>firewall deny src=1.1.1.1",
        ("10.9.8.7", 514),
        settings=get_settings(),
    )
    assert accepted.get("ok") is True
    assert int(accepted.get("accepted") or 0) == 1
    assert accepted.get("data_source") == "SYSLOG"

    events = client.get(
        "/api/monitor/logs/events?q=firewall%20deny",
        headers=auth_headers,
    )
    assert events.status_code == 200
    hit = events.json()["items"][0]
    assert hit["execution_mode"] == "LIVE"
    assert hit["data_source"] == "SYSLOG"
    assert hit["attrs"].get("syslog_source_ip") == "10.9.8.7"


def test_syslog_gate_off_drops_even_with_mapping(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Platform off → syslog capability denied; datagram dropped."""
    tenants_service.ensure_migration_tenant()
    stream_id = _ensure_stream(client, auth_headers)
    # Mapping can exist, but gates off → no LIVE write.
    ingest_service.put_syslog_sources(
        tenant_id=MIGRATION_TENANT_ID,
        sources=[
            {
                "source_ip": "10.0.0.9",
                "stream_id": stream_id,
                "status": "active",
            }
        ],
    )
    monkeypatch.setenv("MONITOR_LIVE_SYSLOG_BIND", "127.0.0.1:5514")
    get_settings.cache_clear()
    result = syslog_receiver.handle_datagram(
        b"<14>should not land",
        ("10.0.0.9", 514),
        settings=get_settings(),
    )
    assert result.get("dropped") is True
    count = require_monitor_database()["log_events"].count_documents(
        {"message": "should not land"}
    )
    assert count == 0


def test_meta_exposes_ingest_paths(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in(client, auth_headers)
    meta = client.get("/api/monitor/meta", headers=auth_headers)
    assert meta.status_code == 200
    body = meta.json()
    assert body["ingest_logs"] == "/api/monitor/ingest/logs"
    assert body["syslog_sources"] == "/api/monitor/logs/syslog-sources"
    assert body["live_gates"]["http_ingest"] is True
    assert body["live_gates"]["syslog_bound"] is False
