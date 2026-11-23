"""Monitoring L4 — agent registration + token auth + mTLS sketch (0.88.0)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import get_settings
from app.db import require_monitor_database
from app.monitor.services import agents as agents_service
from app.monitor.services import mtls as mtls_service
from app.services import entitlements as entitlements_service
from app.services import tenants as tenants_service
from app.tenancy import MIGRATION_TENANT_ID
from tests.frontend_paths import FRONTEND_INDEX


@pytest.fixture()
def live_platform_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "false")
    monkeypatch.setenv("MONITOR_AGENT_MTLS_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def live_platform_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_AGENT_ENABLED", "true")
    monkeypatch.setenv("MONITOR_AGENT_TOKEN_PEPPER", "test-pepper-l4")
    monkeypatch.setenv("MONITOR_AGENT_MTLS_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def live_with_mtls(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_AGENT_ENABLED", "true")
    monkeypatch.setenv("MONITOR_AGENT_TOKEN_PEPPER", "test-pepper-l4")
    monkeypatch.setenv("MONITOR_AGENT_MTLS_ENABLED", "true")
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


def _enroll(client: TestClient, auth_headers: dict[str, str], **extra) -> dict:
    resp = client.post(
        "/api/monitor/agents/enrollments",
        headers=auth_headers,
        json={"label": "lab-agent", **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_version_bump_for_monitor_l4() -> None:
    assert __version__ == "0.88.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.88.0"' in html
    assert "monitor/agents.js?v=0.88.0" in html
    assert 'data-tab="monitor-agents"' in html
    assert 'id="tab-monitor-agents"' in html


def test_monitor_agents_entitlement_in_catalog() -> None:
    starter = entitlements_service.get_plan("starter")
    standard = entitlements_service.get_plan("standard")
    unlimited = entitlements_service.get_plan("legacy_unlimited")
    assert starter["limits"]["monitor_agents"] == 5
    assert standard["limits"]["monitor_agents"] == 50
    assert unlimited["limits"]["monitor_agents"] is None


def test_enroll_and_register_403_when_gates_off(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    enroll = client.post(
        "/api/monitor/agents/enrollments",
        headers=auth_headers,
        json={"label": "blocked"},
    )
    assert enroll.status_code == 403, enroll.text

    register = client.post(
        "/api/monitor/agents/register",
        json={
            "enrollment_code": "menroll_notreal",
            "name": "blocked-agent",
            "os_family": "linux",
        },
    )
    assert register.status_code in {401, 403}, register.text


def test_enroll_register_heartbeat_rotate_revoke(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_agent(client, auth_headers)
    enrollment = _enroll(client, auth_headers)
    code = enrollment["code"]
    assert code.startswith("menroll_")
    assert "code_hash" not in enrollment

    # Single-use register.
    registered = client.post(
        "/api/monitor/agents/register",
        json={
            "enrollment_code": code,
            "name": "edge-01",
            "hostname": "edge-01.lab",
            "os_family": "linux",
            "os_name": "Ubuntu 22.04",
            "version": "0.1.0",
            "labels": {"tier": "lab"},
        },
    )
    assert registered.status_code == 201, registered.text
    body = registered.json()
    agent_id = body["agent_id"]
    token = body["token"]
    assert token.startswith("mat_")
    assert body["status"] == "active"
    assert body["tenant_id"] == MIGRATION_TENANT_ID
    assert "token_hash" not in body

    # Reuse enrollment → conflict / unusable.
    reuse = client.post(
        "/api/monitor/agents/register",
        json={
            "enrollment_code": code,
            "name": "edge-02",
            "os_family": "linux",
        },
    )
    assert reuse.status_code in {401, 409}, reuse.text

    # Token hash-at-rest only.
    db = require_monitor_database()
    stored = db["monitor_agents"].find_one(
        {"tenant_id": MIGRATION_TENANT_ID, "agent_id": agent_id}
    )
    assert stored is not None
    assert stored.get("token_hash")
    assert token not in stored.values()
    assert stored["token_hash"] == agents_service.hash_agent_secret(
        token, pepper="test-pepper-l4"
    )

    # Heartbeat with bearer token.
    hb = client.post(
        f"/api/monitor/agents/{agent_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"version": "0.1.1", "hostname": "edge-01.lab"},
    )
    assert hb.status_code == 200, hb.text
    assert hb.json()["status"] == "active"
    assert hb.json()["version"] == "0.1.1"

    # List agents (session).
    listed = client.get("/api/monitor/agents", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] >= 1
    assert any(i["agent_id"] == agent_id for i in listed.json()["items"])
    assert all("token_hash" not in i for i in listed.json()["items"])

    # Rotate via agent token — old token dies.
    rotated = client.post(
        f"/api/monitor/agents/{agent_id}/rotate-token",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rotated.status_code == 200, rotated.text
    new_token = rotated.json()["token"]
    assert new_token.startswith("mat_")
    assert new_token != token

    old_hb = client.post(
        f"/api/monitor/agents/{agent_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert old_hb.status_code == 401, old_hb.text

    new_hb = client.post(
        f"/api/monitor/agents/{agent_id}/heartbeat",
        headers={"X-Monitor-Agent-Token": new_token},
        json={},
    )
    assert new_hb.status_code == 200, new_hb.text

    # Revoke blocks heartbeat.
    revoked = client.post(
        f"/api/monitor/agents/{agent_id}/revoke",
        headers=auth_headers,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"

    dead = client.post(
        f"/api/monitor/agents/{agent_id}/heartbeat",
        headers={"Authorization": f"Bearer {new_token}"},
        json={},
    )
    assert dead.status_code == 401, dead.text


def test_enrollment_ttl_expiry(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _opt_in_agent(client, auth_headers)
    enrollment = _enroll(client, auth_headers, ttl_seconds=60)
    code = enrollment["code"]

    # Force expiry by rewriting expires_at in the past.
    from datetime import datetime, timedelta, timezone

    db = require_monitor_database()
    db["monitor_agent_enrollments"].update_one(
        {"enrollment_id": enrollment["enrollment_id"]},
        {
            "$set": {
                "expires_at": datetime.now(timezone.utc) - timedelta(seconds=5),
            }
        },
    )
    resp = client.post(
        "/api/monitor/agents/register",
        json={
            "enrollment_code": code,
            "name": "late",
            "os_family": "linux",
        },
    )
    assert resp.status_code == 410, resp.text


def test_heartbeat_403_when_agent_gate_off_after_register(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _opt_in_agent(client, auth_headers)
    enrollment = _enroll(client, auth_headers)
    registered = client.post(
        "/api/monitor/agents/register",
        json={
            "enrollment_code": enrollment["code"],
            "name": "temp",
            "os_family": "windows",
        },
    )
    assert registered.status_code == 201, registered.text
    token = registered.json()["token"]
    agent_id = registered.json()["agent_id"]

    # Turn off tenant agent opt-in.
    off = client.patch(
        "/api/monitor/admin/live-settings",
        headers=auth_headers,
        json={"monitor_live_agent_opt_in": False},
    )
    assert off.status_code == 200, off.text

    hb = client.post(
        f"/api/monitor/agents/{agent_id}/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert hb.status_code == 403, hb.text


def test_mtls_sketch_heartbeat(
    live_with_mtls,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _opt_in_agent(client, auth_headers)
    enrollment = _enroll(client, auth_headers)
    registered = client.post(
        "/api/monitor/agents/register",
        json={
            "enrollment_code": enrollment["code"],
            "name": "mtls-agent",
            "os_family": "macos",
            "mtls_fingerprint": "fp-lab-1",
        },
    )
    assert registered.status_code == 201, registered.text
    agent_id = registered.json()["agent_id"]

    meta = client.get("/api/monitor/meta", headers=auth_headers)
    assert meta.status_code == 200, meta.text
    assert meta.json()["agent_mtls"]["enabled"] is True
    assert meta.json()["agents"] == "/api/monitor/agents"

    # mTLS headers (proxy stub) — no bearer token.
    hb = client.post(
        f"/api/monitor/agents/{agent_id}/heartbeat",
        headers={
            "X-SSL-Client-Verify": "SUCCESS",
            "X-SSL-Client-S-DN": f"CN=svrmon-agent,OU={agent_id},O=svrmon24",
            "X-SSL-Client-Tenant": MIGRATION_TENANT_ID,
            "X-SSL-Client-Fingerprint": "fp-lab-1",
        },
        json={"version": "mtls-1"},
    )
    assert hb.status_code == 200, hb.text
    assert hb.json()["version"] == "mtls-1"

    # mTLS disabled → same headers ignored → 401.
    monkeypatch.setenv("MONITOR_AGENT_MTLS_ENABLED", "false")
    get_settings.cache_clear()
    denied = client.post(
        f"/api/monitor/agents/{agent_id}/heartbeat",
        headers={
            "X-SSL-Client-Verify": "SUCCESS",
            "X-SSL-Client-OU": agent_id,
            "X-SSL-Client-Tenant": MIGRATION_TENANT_ID,
        },
        json={},
    )
    assert denied.status_code == 401, denied.text
    get_settings.cache_clear()


def test_mtls_parse_helpers() -> None:
    assert mtls_service.parse_subject_ou("CN=a,OU=agt-abc,O=x") == "agt-abc"
    assert (
        mtls_service.parse_tenant_from_san_hint(
            "URI:svrmon24:tenant/tenant-svrmon24-legacy"
        )
        == "tenant-svrmon24-legacy"
    )
    assert mtls_service.extract_mtls_identity({}) is None


def test_agents_admin_tab_shell_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'id="magEnroll"' in html
    assert 'id="magAgentsTable"' in html
    assert "monitor-agents-toolbar" in html
    js = (FRONTEND_INDEX.parent / "static/js/monitor/agents.js").read_text(
        encoding="utf-8"
    )
    assert "/api/monitor/agents/enrollments" in js
    assert "SVRMON24MonitorAgents" in js
