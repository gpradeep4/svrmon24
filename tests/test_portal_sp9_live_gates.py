"""Service Portal SP9 — live gate stubs (fail-closed; SP10 unlocks adapters) (0.99.8)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import Settings, get_settings
from app.portal.services import live_gates as live_gates_service
from app.services import tenants as tenants_service
from app.tenancy import MIGRATION_TENANT_ID

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_portal_sp9() -> None:
    assert __version__ == "0.99.8"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.8"' in html


def test_platform_live_flags_default_off() -> None:
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert settings.service_portal_live_exec_enabled is False
    assert settings.service_portal_live_agentless_enabled is True
    assert settings.service_portal_live_agent_enabled is True
    assert (settings.service_portal_egress_allowlist or "") == ""
    get_settings.cache_clear()


@pytest.mark.usefixtures("clean_db")
def test_meta_live_gates_fail_closed(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/portal/meta", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["live_exec"] is False
    assert body["execution_mode"] == "SIMULATED"
    assert body["live_gates"]["fail_closed"] is True
    assert body["live_gates"]["live_exec"] is False
    assert body["live_gates"]["platform_enabled"] is False
    # SP10: adapter code is unlocked; effective LIVE still requires gates.
    assert body.get("live_adapters") is True
    assert body["live_gates"]["live_adapters"] is True


@pytest.mark.usefixtures("clean_db")
def test_admin_live_settings_get_and_patch(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    got = client.get("/api/portal/admin/live-settings", headers=auth_headers)
    assert got.status_code == 200, got.text
    payload = got.json()
    assert payload["platform"]["SERVICE_PORTAL_LIVE_EXEC_ENABLED"] is False
    assert payload["tenant"]["sp_live_opt_in"] is False
    assert payload["effective"]["live_exec"] is False
    assert payload["live_adapters"] is True

    patched = client.patch(
        "/api/portal/admin/live-settings",
        headers=auth_headers,
        json={"sp_live_opt_in": True, "sp_live_agentless_opt_in": True},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["tenant"]["sp_live_opt_in"] is True
    assert body["tenant"]["sp_live_agentless_opt_in"] is True
    # Platform master still off → effective remains false.
    assert body["effective"]["live_exec"] is False


@pytest.mark.usefixtures("clean_db")
def test_assert_live_allowed_requires_both_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenants_service.ensure_migration_tenant()
    tenants_service.set_portal_live_settings(
        MIGRATION_TENANT_ID,
        {
            "sp_live_opt_in": True,
            "sp_live_agentless_opt_in": True,
            "sp_live_agent_opt_in": True,
        },
    )
    # Platform still off → deny.
    get_settings.cache_clear()
    with pytest.raises(Exception) as excinfo:
        live_gates_service.assert_live_allowed(
            tenant_id=MIGRATION_TENANT_ID, capability="live_exec"
        )
    assert getattr(excinfo.value, "status_code", None) == 403

    monkeypatch.setenv("SERVICE_PORTAL_LIVE_EXEC_ENABLED", "true")
    get_settings.cache_clear()
    # Both open — assert passes; SP10 adapters are unlocked.
    live_gates_service.assert_live_allowed(
        tenant_id=MIGRATION_TENANT_ID, capability="live_exec"
    )
    gates = live_gates_service.live_gates(tenant_id=MIGRATION_TENANT_ID)
    assert gates["live_exec"] is True
    assert gates["live_adapters"] is True
    get_settings.cache_clear()


@pytest.mark.usefixtures("clean_db")
def test_live_enqueue_allowed_when_gates_open(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gates open → LIVE enqueue succeeds (SP10 unlock)."""
    monkeypatch.setenv("SERVICE_PORTAL_LIVE_EXEC_ENABLED", "true")
    monkeypatch.setenv("SERVICE_PORTAL_LIVE_AGENTLESS_ENABLED", "true")
    get_settings.cache_clear()
    tenants_service.ensure_migration_tenant()
    tenants_service.set_portal_live_settings(
        MIGRATION_TENANT_ID,
        {
            "sp_live_opt_in": True,
            "sp_live_agentless_opt_in": True,
        },
    )

    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200
    item = next(
        i
        for i in client.get("/api/portal/catalog", headers=auth_headers).json()["items"]
        if i["key"] == "generic.daily.access_request"
    )
    created = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": item["item_id"],
            "form_values": {
                "who": "eve",
                "what": "vpn",
                "why": "demo",
                "duration_days": 3,
            },
            "requested_execution_mode": "LIVE",
            "submit": True,
        },
    )
    assert created.status_code == 200, created.text
    req = created.json()
    client.post(
        f"/api/itsm/changes/{req['change_id']}/transition",
        headers=auth_headers,
        json={"status": "approved"},
    )
    synced = client.post(
        f"/api/portal/changes/{req['request_id']}/sync",
        headers=auth_headers,
    )
    assert synced.status_code == 200
    runs = client.get(
        "/api/portal/executions",
        headers=auth_headers,
        params={"request_id": req["request_id"]},
    )
    assert runs.status_code == 200
    # Auto-enqueue on approve should create a LIVE run when gates open.
    assert runs.json()["total"] >= 1
    assert runs.json()["items"][0]["execution_mode"] == "LIVE"
    get_settings.cache_clear()
