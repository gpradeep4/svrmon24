"""Monitoring L2 — agentless ICMP + SNMP executors + secret_ref + rollup (0.99.13)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import get_settings
from app.db import require_monitor_database
from app.monitor.models.checks import L2_PROTOCOLS, NETWORK_CHECK_EXAMPLES
from app.monitor.services import executors
from app.monitor.services import secrets as secrets_service
from app.services import tenants as tenants_service
from app.tenancy import MIGRATION_TENANT_ID
from tests.frontend_paths import FRONTEND_INDEX


@pytest.fixture()
def live_with_allowlist(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "true")
    monkeypatch.setenv("MONITOR_LIVE_AGENTLESS_ENABLED", "true")
    monkeypatch.setenv("MONITOR_EGRESS_ALLOWLIST", "example.com,127.0.0.1,::1,lab.example")
    monkeypatch.setenv("MONITOR_POLLER_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def live_platform_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "false")
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


def _ensure_target(client: TestClient, auth_headers: dict[str, str], *, target_id: str = "tgt-net-1") -> str:
    """Insert a monitor target document directly for rollup tests."""
    db = require_monitor_database()
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    db["monitor_targets"].update_one(
        {"target_id": target_id, "tenant_id": MIGRATION_TENANT_ID},
        {
            "$set": {
                "target_id": target_id,
                "component_id": "cmp-net-1",
                "component_type": "Network",
                "name_snapshot": "lab-switch",
                "domain": "network",
                "target_kind": "switch",
                "collect_mode": "AGENTLESS",
                "status": "unknown",
                "execution_mode": "SIMULATED",
                "data_source": "SYNTHETIC_DEMO",
                "check_ids": [],
                "tenant_id": MIGRATION_TENANT_ID,
                "updated_at": now,
                "created_at": now,
            }
        },
        upsert=True,
    )
    return target_id


def test_version_bump_for_monitor_l2() -> None:
    assert __version__ == "0.99.13"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.13"' in html
    assert "monitor/targets.js?v=0.99.13" in html
    assert 'id="mtSrvBanner"' in html
    assert 'id="mtNetBanner"' in html
    assert ">Mode</th>" in html


def test_l2_protocols_and_network_examples() -> None:
    assert L2_PROTOCOLS == ("http", "tcp", "icmp", "snmp")
    kinds = {ex["target_kind"] for ex in NETWORK_CHECK_EXAMPLES}
    assert {"switch", "router", "firewall", "load_balancer", "access_point"} <= kinds
    assert any(ex["protocol"] == "snmp" for ex in NETWORK_CHECK_EXAMPLES)
    assert any(ex["protocol"] == "icmp" for ex in NETWORK_CHECK_EXAMPLES)


def test_secret_ref_env_and_insecure() -> None:
    ref, insecure = secrets_service.normalize_secret_ref("env:SNMP_COMMUNITY_LAB")
    assert ref == "env:SNMP_COMMUNITY_LAB"
    assert insecure is False

    ref2, insecure2 = secrets_service.normalize_secret_ref("insecure:public")
    assert insecure2 is True
    assert ref2.startswith("insecure:")

    with pytest.raises(secrets_service.SecretRefError):
        secrets_service.normalize_secret_ref("not a valid ref!!")


def test_snmp_secret_ref_mock_writes_live(
    live_with_allowlist,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SNMP_COMMUNITY_LAB", "labcommunity")
    _opt_in_agentless(client, auth_headers)
    target_id = _ensure_target(client, auth_headers)

    created = client.post(
        "/api/monitor/checks",
        headers=auth_headers,
        json={
            "target_id": target_id,
            "protocol": "snmp",
            "endpoint": {
                "host": "example.com",
                "port": 161,
                "oid": "1.3.6.1.2.1.1.3.0",
            },
            "secret_ref": "env:SNMP_COMMUNITY_LAB",
            "timeout_seconds": 2,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["protocol"] == "snmp"
    assert body["secret_ref"] == "env:SNMP_COMMUNITY_LAB"
    assert body["secret_insecure_demo"] is False
    check_id = body["check_id"]

    fake = {
        "ok": True,
        "latency_ms": 4.2,
        "value": 12345.0,
        "message": "snmp oid mock = 12345",
        "denied": False,
        "secret_insecure_demo": False,
        "oid": "1.3.6.1.2.1.1.3.0",
    }
    with patch(
        "app.monitor.services.executors.snmp_get_oid",
        return_value=fake,
    ) as mocked:
        resp = client.post(
            f"/api/monitor/checks/{check_id}/run-once", headers=auth_headers
        )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["live_written"] is True
    assert out["execution_mode"] == "LIVE"
    assert out["sample"]["data_source"] == "SNMP"
    assert out["sample"]["metric_name"] == "check.snmp.oid"
    assert out["sample"]["value"] == 12345.0
    assert out["secret_insecure_demo"] is False
    mocked.assert_called_once()
    assert mocked.call_args.kwargs["community"] == "labcommunity"

    # Target rollup stamped LIVE.
    db = require_monitor_database()
    target = db["monitor_targets"].find_one(
        {"target_id": target_id, "tenant_id": MIGRATION_TENANT_ID}
    )
    assert target is not None
    assert target["execution_mode"] == "LIVE"
    assert target["status"] == "healthy"
    assert check_id in (target.get("check_ids") or [])
    assert target.get("live_status_reason")


def test_snmp_plaintext_demo_flagged(
    live_with_allowlist,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_agentless(client, auth_headers)
    target_id = _ensure_target(client, auth_headers, target_id="tgt-fw-1")
    created = client.post(
        "/api/monitor/checks",
        headers=auth_headers,
        json={
            "target_id": target_id,
            "protocol": "snmp",
            "endpoint": {"host": "example.com", "oid": "1.3.6.1.2.1.1.5.0"},
            "secret_ref": "insecure:public",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["secret_insecure_demo"] is True

    with patch(
        "app.monitor.services.executors.snmp_get_oid",
        return_value={
            "ok": True,
            "latency_ms": 1.0,
            "value": 1.0,
            "message": "ok",
        },
    ):
        resp = client.post(
            f"/api/monitor/checks/{created.json()['check_id']}/run-once",
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["secret_insecure_demo"] is True
    assert resp.json()["result"]["secret_insecure_demo"] is True


def test_snmp_requires_secret_ref(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    tenants_service.ensure_migration_tenant()
    resp = client.post(
        "/api/monitor/checks",
        headers=auth_headers,
        json={
            "target_id": "tgt-1",
            "protocol": "snmp",
            "endpoint": {"host": "example.com"},
        },
    )
    assert resp.status_code == 422, resp.text


def test_icmp_unavailable_no_crash(
    live_with_allowlist,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_agentless(client, auth_headers)
    target_id = _ensure_target(client, auth_headers, target_id="tgt-icmp-1")
    created = client.post(
        "/api/monitor/checks",
        headers=auth_headers,
        json={
            "target_id": target_id,
            "protocol": "icmp",
            "endpoint": {"host": "example.com"},
            "timeout_seconds": 1,
        },
    )
    assert created.status_code == 201, created.text
    check_id = created.json()["check_id"]

    unavailable = {
        "ok": False,
        "latency_ms": None,
        "value": None,
        "message": "icmp unavailable: permission denied for ping (needs CAP_NET_RAW)",
        "denied": False,
        "skipped": True,
    }
    with patch(
        "app.monitor.services.executors._ping_via_subprocess",
        return_value=unavailable,
    ), patch(
        "app.monitor.services.executors._try_raw_icmp_socket",
        return_value=(None, "raw ICMP socket requires CAP_NET_RAW / root"),
    ):
        resp = client.post(
            f"/api/monitor/checks/{check_id}/run-once", headers=auth_headers
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is False
    assert body["live_written"] is True  # structured error still records LIVE
    assert "unavailable" in (body["message"] or "").lower()
    assert body["sample"]["data_source"] == "ICMP_CHECK"


def test_icmp_success_writes_live(
    live_with_allowlist,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    _opt_in_agentless(client, auth_headers)
    target_id = _ensure_target(client, auth_headers, target_id="tgt-icmp-ok")
    created = client.post(
        "/api/monitor/checks",
        headers=auth_headers,
        json={
            "target_id": target_id,
            "protocol": "icmp",
            "endpoint": {"host": "example.com"},
        },
    )
    assert created.status_code == 201, created.text
    check_id = created.json()["check_id"]
    with patch(
        "app.monitor.services.executors._ping_via_subprocess",
        return_value={
            "ok": True,
            "latency_ms": 3.5,
            "value": 3.5,
            "message": "icmp echo ok example.com",
            "denied": False,
            "skipped": False,
        },
    ):
        resp = client.post(
            f"/api/monitor/checks/{check_id}/run-once", headers=auth_headers
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert resp.json()["live_written"] is True
    assert resp.json()["sample"]["data_source"] == "ICMP_CHECK"


def test_icmp_run_once_403_when_gates_off(
    live_platform_off,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    created = client.post(
        "/api/monitor/checks",
        headers=auth_headers,
        json={
            "target_id": "tgt-1",
            "protocol": "icmp",
            "endpoint": {"host": "example.com"},
        },
    )
    assert created.status_code == 201, created.text
    resp = client.post(
        f"/api/monitor/checks/{created.json()['check_id']}/run-once",
        headers=auth_headers,
    )
    assert resp.status_code == 403, resp.text


def test_icmp_executor_never_raises_on_ping_crash() -> None:
    """Poller safety: subprocess OSError becomes structured outcome."""
    with patch(
        "app.monitor.services.executors.shutil.which", return_value="/bin/ping"
    ), patch(
        "app.monitor.services.executors.subprocess.run",
        side_effect=OSError("boom"),
    ), patch(
        "app.monitor.services.executors.assert_egress_allowed",
        return_value=["1.2.3.4"],
    ), patch(
        "app.monitor.services.executors._try_raw_icmp_socket",
        return_value=(None, "raw unavailable"),
    ):
        out = executors.execute_icmp_check(
            endpoint={"host": "example.com"},
            timeout_seconds=1,
            platform_allowlist="example.com",
        )
    assert out["ok"] is False
    assert out.get("skipped") is True
    assert "unavailable" in out["message"].lower()


def test_frontend_targets_has_live_mode_badges() -> None:
    js = (FRONTEND_INDEX.parent / "static/js/monitor/targets.js").read_text(
        encoding="utf-8"
    )
    assert "modeBadge" in js
    assert "monitor-mode-live" in js
    assert "execution_mode" in js
    assert "mtSrvBanner" in js or "Banner" in js
    assert "LIVE" in js
