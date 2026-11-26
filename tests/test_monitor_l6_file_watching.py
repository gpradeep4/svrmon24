"""Monitoring L6 — live file watching (watch_mode + agentless poll) (0.99.8)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import get_settings
from app.db import require_monitor_database
from app.monitor.services import file_monitoring as file_service
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
    monkeypatch.setenv("MONITOR_LIVE_AGENT_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_AGENTLESS_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_HTTP_INGEST_ENABLED", "true")
    monkeypatch.setenv("MONITOR_AGENT_TOKEN_PEPPER", "test-pepper-l6")
    monkeypatch.setenv("MONITOR_EGRESS_ALLOWLIST", "example.com,127.0.0.1,localhost")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    file_service.set_checksum_fetcher(None)


def _opt_in_live(client: TestClient, auth_headers: dict[str, str]) -> None:
    tenants_service.ensure_migration_tenant()
    resp = client.patch(
        "/api/monitor/admin/live-settings",
        headers=auth_headers,
        json={
            "monitor_live_opt_in": True,
            "monitor_live_agent_opt_in": True,
            "monitor_live_agentless_opt_in": True,
        },
    )
    assert resp.status_code == 200, resp.text


def _register_agent(
    client: TestClient,
    auth_headers: dict[str, str],
    *,
    os_family: str = "linux",
) -> dict:
    enroll = client.post(
        "/api/monitor/agents/enrollments",
        headers=auth_headers,
        json={"label": "l6-agent"},
    )
    assert enroll.status_code == 201, enroll.text
    registered = client.post(
        "/api/monitor/agents/register",
        json={
            "enrollment_code": enroll.json()["code"],
            "name": "l6-edge",
            "hostname": "l6-edge.lab",
            "os_family": os_family,
            "os_name": os_family,
            "version": "0.99.8-fixture",
        },
    )
    assert registered.status_code == 201, registered.text
    return registered.json()


def test_version_bump_for_monitor_l6() -> None:
    assert __version__ == "0.99.8"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.8"' in html
    assert 'data-fm-watch-mode="1"' in html
    assert "monitor/index.js?v=0.99.8" in html


def test_meta_exposes_watch_modes_and_files_api(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_live(client, auth_headers)
    meta = client.get("/api/monitor/meta", headers=auth_headers)
    assert meta.status_code == 200, meta.text
    body = meta.json()
    assert body["files_watches"] == "/api/monitor/files/watches"
    assert body["watch_modes"] == ["SIMULATED", "AGENT", "AGENTLESS_POLL"]
    contract = body["agent_ingest_contract"]
    assert "agent_watcher_schema" in contract
    assert contract["agent_watcher_schema"]["data_source"] == "AGENT_FILE_WATCH"


def test_simulated_watch_unchanged_when_mode_simulated(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    listed = client.get("/api/monitor/files/watches", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["live_watching"] is False
    assert body["total"] >= 4
    for item in body["items"]:
        assert item.get("watch_mode", "SIMULATED") == "SIMULATED"
        assert item["execution_mode"] == "SIMULATED"

    watch_id = body["items"][0]["watch_id"]
    versions = client.get(
        f"/api/monitor/files/watches/{watch_id}/versions",
        headers=auth_headers,
    )
    assert versions.status_code == 200, versions.text
    for ev in versions.json()["items"]:
        assert ev["execution_mode"] == "SIMULATED"
        assert ev["data_source"] == "SYNTHETIC_DEMO"


def test_patch_live_mode_403_when_gates_off(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    listed = client.get("/api/monitor/files/watches", headers=auth_headers)
    watch_id = listed.json()["items"][0]["watch_id"]
    resp = client.patch(
        f"/api/monitor/files/watches/{watch_id}",
        headers=auth_headers,
        json={"watch_mode": "AGENT", "agent_id": "agt-missing"},
    )
    assert resp.status_code == 403, resp.text


def test_agent_mode_ingest_live_events(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_live(client, auth_headers)
    agent = _register_agent(client, auth_headers)
    listed = client.get("/api/monitor/files/watches", headers=auth_headers)
    watch_id = listed.json()["items"][0]["watch_id"]

    # SIMULATED watch rejects agent events until patched.
    blocked = client.post(
        "/api/monitor/ingest/file-events",
        headers={"Authorization": f"Bearer {agent['token']}"},
        json={
            "os_family": "linux",
            "seq": 1,
            "events": [
                {
                    "watch_id": watch_id,
                    "change_kind": "modified",
                    "os_watcher": "inotify",
                    "version": 99,
                    "summary": "should reject",
                }
            ],
        },
    )
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["accepted"] == 0
    assert blocked.json()["rejected"] == 1

    patched = client.patch(
        f"/api/monitor/files/watches/{watch_id}",
        headers=auth_headers,
        json={
            "watch_mode": "AGENT",
            "agent_id": agent["agent_id"],
            "os_watcher": "inotify",
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["watch_mode"] == "AGENT"
    assert patched.json()["execution_mode"] == "LIVE"

    files = client.post(
        "/api/monitor/ingest/file-events",
        headers={"Authorization": f"Bearer {agent['token']}"},
        json={
            "os_family": "linux",
            "seq": 2,
            "events": [
                {
                    "watch_id": watch_id,
                    "change_kind": "modified",
                    "os_watcher": "inotify",
                    "version": 100,
                    "summary": "L6 agent live change",
                    "content_hash": "sha256:l6-agent",
                }
            ],
        },
    )
    assert files.status_code == 200, files.text
    assert files.json()["accepted"] == 1
    assert files.json()["execution_mode"] == "LIVE"
    assert files.json()["data_source"] == "AGENT_FILE_WATCH"

    db = require_monitor_database()
    hit = db["file_version_events"].find_one(
        {
            "tenant_id": MIGRATION_TENANT_ID,
            "watch_id": watch_id,
            "execution_mode": "LIVE",
            "data_source": "AGENT_FILE_WATCH",
            "version": 100,
        }
    )
    assert hit is not None
    assert hit["os_watcher"] == "inotify"


def test_agentless_poll_checksum_with_test_double(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_live(client, auth_headers)
    listed = client.get("/api/monitor/files/watches", headers=auth_headers)
    watch_id = listed.json()["items"][1]["watch_id"]

    state = {"hash": "etag:v1", "calls": 0}

    def fake_fetch(**kwargs):
        state["calls"] += 1
        return {
            "ok": True,
            "content_hash": state["hash"],
            "size_bytes": 42,
            "message": "checksum ok",
            "denied": False,
        }

    file_service.set_checksum_fetcher(fake_fetch)

    patched = client.patch(
        f"/api/monitor/files/watches/{watch_id}",
        headers=auth_headers,
        json={
            "watch_mode": "AGENTLESS_POLL",
            "poll_url": "https://example.com/config.env",
            "poll_method": "HEAD",
            "poll_interval_seconds": 30,
            "egress_allowlist": ["example.com"],
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["watch_mode"] == "AGENTLESS_POLL"
    assert patched.json()["execution_mode"] == "LIVE"

    # First poll baselines without a modified event (unless force).
    first = client.post(
        f"/api/monitor/files/watches/{watch_id}/poll-once",
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["ok"] is True
    assert body["data_source"] == "AGENTLESS_FILE_POLL"
    assert body["changed"] is False
    assert state["calls"] == 1

    # Change checksum → LIVE event.
    state["hash"] = "etag:v2"
    second = client.post(
        f"/api/monitor/files/watches/{watch_id}/poll-once",
        headers=auth_headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["changed"] is True
    assert second.json()["execution_mode"] == "LIVE"
    event = second.json()["event"]
    assert event["data_source"] == "AGENTLESS_FILE_POLL"
    assert event["execution_mode"] == "LIVE"
    assert event["content_hash"] == "etag:v2"

    db = require_monitor_database()
    count = db["file_version_events"].count_documents(
        {
            "tenant_id": MIGRATION_TENANT_ID,
            "watch_id": watch_id,
            "data_source": "AGENTLESS_FILE_POLL",
        }
    )
    assert count >= 1


def test_agentless_poll_403_when_gates_off(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    listed = client.get("/api/monitor/files/watches", headers=auth_headers)
    watch_id = listed.json()["items"][0]["watch_id"]
    # Cannot set AGENTLESS_POLL without gates.
    resp = client.patch(
        f"/api/monitor/files/watches/{watch_id}",
        headers=auth_headers,
        json={
            "watch_mode": "AGENTLESS_POLL",
            "poll_url": "https://example.com/x",
        },
    )
    assert resp.status_code == 403, resp.text


def test_ui_exposes_watch_mode_selector() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'id="fmWatchMode"' in html
    assert 'data-fm-save-mode="1"' in html
    assert ">AGENTLESS_POLL<" in html
    js = (FRONTEND_INDEX.parent / "static/js/cmdb.js").read_text(encoding="utf-8")
    assert "/api/monitor/files/watches" in js
    assert "saveFileMonitoringMode" in js
