"""Monitoring L5 — agent metrics/logs/file-events ingest + multi-OS contract (0.99.2)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import get_settings
from app.db import require_monitor_database
from app.monitor.services import agent_ingest as agent_ingest_service
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
    monkeypatch.setenv("MONITOR_LIVE_HTTP_INGEST_ENABLED", "true")
    monkeypatch.setenv("MONITOR_AGENT_TOKEN_PEPPER", "test-pepper-l5")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _opt_in_agent(client: TestClient, auth_headers: dict[str, str]) -> None:
    tenants_service.ensure_migration_tenant()
    resp = client.patch(
        "/api/monitor/admin/live-settings",
        headers=auth_headers,
        json={
            "monitor_live_opt_in": True,
            "monitor_live_agent_opt_in": True,
        },
    )
    assert resp.status_code == 200, resp.text


def _register_agent(
    client: TestClient,
    auth_headers: dict[str, str],
    *,
    os_family: str = "linux",
    name: str = "fixture-edge",
) -> dict:
    enroll = client.post(
        "/api/monitor/agents/enrollments",
        headers=auth_headers,
        json={"label": f"l5-{os_family}"},
    )
    assert enroll.status_code == 201, enroll.text
    registered = client.post(
        "/api/monitor/agents/register",
        json={
            "enrollment_code": enroll.json()["code"],
            "name": name,
            "hostname": f"{name}.lab",
            "os_family": os_family,
            "os_name": os_family,
            "version": "0.99.2-fixture",
        },
    )
    assert registered.status_code == 201, registered.text
    return registered.json()


def _ensure_stream(client: TestClient, auth_headers: dict[str, str]) -> str:
    listed = client.get("/api/monitor/logs/streams", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert items, "expected default streams"
    return items[0]["stream_id"]


def _agent_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_version_bump_for_monitor_l5() -> None:
    assert __version__ == "0.99.2"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.2"' in html
    assert "monitor/agents.js?v=0.99.2" in html


def test_meta_exposes_agent_ingest_contract(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_agent(client, auth_headers)
    meta = client.get("/api/monitor/meta", headers=auth_headers)
    assert meta.status_code == 200, meta.text
    body = meta.json()
    assert body["ingest_metrics"] == "/api/monitor/ingest/metrics"
    assert body["ingest_file_events"] == "/api/monitor/ingest/file-events"
    contract = body["agent_ingest_contract"]
    assert set(contract["os_families"]) == {"linux", "windows", "macos", "unix"}
    assert "cpu.usage_pct" in contract["core_metrics"]
    assert contract["os_watchers"]["linux"] == "inotify"
    assert contract["os_watchers"]["windows"] == "readdirectorychanges"


def test_agent_ingest_403_when_gates_off(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    for path in (
        "/api/monitor/ingest/metrics",
        "/api/monitor/ingest/file-events",
    ):
        resp = client.post(path, headers=auth_headers)
        assert resp.status_code == 403, path


@pytest.mark.parametrize("os_family", ["linux", "windows", "macos", "unix"])
def test_fixture_agent_pushes_live_for_each_os_family(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
    os_family: str,
) -> None:
    _opt_in_agent(client, auth_headers)
    agent = _register_agent(
        client, auth_headers, os_family=os_family, name=f"edge-{os_family}"
    )
    token = agent["token"]
    agent_id = agent["agent_id"]
    stream_id = _ensure_stream(client, auth_headers)
    watcher = agent_ingest_service.OS_WATCHERS[os_family]

    # Desired-state: admin sets stream; agent pulls it.
    patched = client.patch(
        f"/api/monitor/agents/{agent_id}/desired-state",
        headers=auth_headers,
        json={"stream_ids": [stream_id], "watch_ids": ["fw-demo-nginx-conf"]},
    )
    assert patched.status_code == 200, patched.text
    assert stream_id in patched.json()["stream_ids"]

    desired = client.get(
        f"/api/monitor/agents/{agent_id}/desired-state",
        headers=_agent_headers(token),
    )
    assert desired.status_code == 200, desired.text
    assert desired.json()["os_watcher"] == watcher
    assert stream_id in desired.json()["stream_ids"]

    metrics = client.post(
        "/api/monitor/ingest/metrics",
        headers=_agent_headers(token),
        json={
            "os_family": os_family,
            "seq": 1,
            "samples": [
                {"metric_name": "cpu.usage_pct", "value": 12.5, "unit": "%"},
                {"metric_name": "mem.used_pct", "value": 55.0, "unit": "%"},
                {"metric_name": "disk.used_pct", "value": 40.0, "unit": "%"},
            ],
        },
    )
    assert metrics.status_code == 200, metrics.text
    mbody = metrics.json()
    assert mbody["accepted"] == 3
    assert mbody["execution_mode"] == "LIVE"
    assert mbody["data_source"] == "AGENT"
    assert mbody["os_family"] == os_family
    assert mbody.get("deduped") is False

    logs = client.post(
        "/api/monitor/ingest/logs",
        headers=_agent_headers(token),
        json={
            "os_family": os_family,
            "stream_id": stream_id,
            "seq": 1,
            "events": [
                {
                    "severity": "info",
                    "message": f"L5 agent log os_family={os_family}",
                }
            ],
        },
    )
    assert logs.status_code == 200, logs.text
    assert logs.json()["accepted"] == 1
    assert logs.json()["data_source"] == "AGENT"
    assert logs.json()["execution_mode"] == "LIVE"

    files = client.post(
        "/api/monitor/ingest/file-events",
        headers=_agent_headers(token),
        json={
            "os_family": os_family,
            "seq": 1,
            "events": [
                {
                    "path": f"/tmp/l5-{os_family}.conf",
                    "change_kind": "modified",
                    "os_watcher": watcher,
                    "summary": f"L5 file change {os_family}",
                    "version": 1,
                }
            ],
        },
    )
    assert files.status_code == 200, files.text
    fbody = files.json()
    assert fbody["accepted"] == 1
    assert fbody["execution_mode"] == "LIVE"
    assert fbody["data_source"] == "AGENT_FILE_WATCH"
    assert fbody["os_watcher"] == watcher

    db = require_monitor_database()
    samples = list(
        db["metric_samples"].find(
            {
                "tenant_id": MIGRATION_TENANT_ID,
                "agent_id": agent_id,
                "execution_mode": "LIVE",
            }
        )
    )
    assert len(samples) == 3
    assert all(s["os_family"] == os_family for s in samples)

    log_hit = db["log_events"].find_one(
        {
            "tenant_id": MIGRATION_TENANT_ID,
            "message": {"$regex": f"os_family={os_family}"},
            "execution_mode": "LIVE",
            "data_source": "AGENT",
        }
    )
    assert log_hit is not None

    file_hit = db["file_version_events"].find_one(
        {
            "tenant_id": MIGRATION_TENANT_ID,
            "agent_id": agent_id,
            "execution_mode": "LIVE",
            "data_source": "AGENT_FILE_WATCH",
        }
    )
    assert file_hit is not None
    assert file_hit["os_watcher"] == watcher


def test_ingest_cursor_dedup(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_agent(client, auth_headers)
    agent = _register_agent(client, auth_headers)
    token = agent["token"]
    payload = {
        "os_family": "linux",
        "seq": 5,
        "samples": [{"metric_name": "cpu.usage_pct", "value": 1.0, "unit": "%"}],
    }
    first = client.post(
        "/api/monitor/ingest/metrics",
        headers=_agent_headers(token),
        json=payload,
    )
    assert first.status_code == 200, first.text
    assert first.json()["accepted"] == 1
    assert first.json()["last_seq"] == 5

    replay = client.post(
        "/api/monitor/ingest/metrics",
        headers=_agent_headers(token),
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["deduped"] is True
    assert replay.json()["accepted"] == 0
    assert replay.json()["duplicate"] is True

    db = require_monitor_database()
    count = db["metric_samples"].count_documents(
        {"tenant_id": MIGRATION_TENANT_ID, "agent_id": agent["agent_id"]}
    )
    assert count == 1

    cursor = db["monitor_ingest_cursors"].find_one(
        {
            "tenant_id": MIGRATION_TENANT_ID,
            "agent_id": agent["agent_id"],
            "channel": "metrics",
        }
    )
    assert cursor is not None
    assert cursor["last_seq"] == 5


def test_os_family_mismatch_rejected(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_agent(client, auth_headers)
    agent = _register_agent(client, auth_headers, os_family="linux")
    resp = client.post(
        "/api/monitor/ingest/metrics",
        headers=_agent_headers(agent["token"]),
        json={
            "os_family": "windows",
            "samples": [{"metric_name": "cpu.usage_pct", "value": 1.0}],
        },
    )
    assert resp.status_code == 422, resp.text


def test_revoked_agent_cannot_ingest(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_agent(client, auth_headers)
    agent = _register_agent(client, auth_headers)
    token = agent["token"]
    agent_id = agent["agent_id"]
    revoke = client.post(
        f"/api/monitor/agents/{agent_id}/revoke",
        headers=auth_headers,
    )
    assert revoke.status_code == 200, revoke.text
    resp = client.post(
        "/api/monitor/ingest/metrics",
        headers=_agent_headers(token),
        json={
            "samples": [{"metric_name": "cpu.usage_pct", "value": 9.0}],
        },
    )
    assert resp.status_code == 401, resp.text


def test_fixture_client_payload_shapes() -> None:
    from agents.fixture_client import OS_WATCHERS, build_payloads

    for family in sorted(OS_WATCHERS):
        payloads = build_payloads(os_family=family, stream_id="ls-demo", seq=1)
        assert payloads["metrics"]["os_family"] == family
        assert len(payloads["metrics"]["samples"]) == 3
        assert payloads["file_events"]["events"][0]["os_watcher"] == OS_WATCHERS[family]
        assert payloads["logs"]["stream_id"] == "ls-demo"
