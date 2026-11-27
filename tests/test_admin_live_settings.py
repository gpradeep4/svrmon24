"""Unified admin live / runtime settings — RBAC, persistence, fail-closed (0.99.10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import Settings, get_settings
from app.services import live_settings as live_settings_service
from app.services import tenants as tenants_service
from app.tenancy import MIGRATION_TENANT_ID

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_unified_live_settings() -> None:
    assert __version__ == "0.99.10"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.10"' in html
    assert 'data-tab="live-runtime"' in html
    assert "Live / Runtime" in html


def test_platform_live_masters_default_off() -> None:
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert settings.monitor_live_probes_enabled is False
    assert settings.service_portal_live_exec_enabled is False
    assert settings.diagnostics_live_enabled is False
    assert settings.itsm_automation_enabled is False
    get_settings.cache_clear()


@pytest.mark.usefixtures("clean_db")
def test_unified_live_settings_get_and_patch(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    got = client.get("/api/admin/live-settings", headers=auth_headers)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["fail_closed"] is True
    assert body["can_write"] is True
    assert "monitoring" in body["modules"]
    assert "portal" in body["modules"]
    assert "diagnostics" in body["modules"]
    assert "itsm_automation" in body["modules"]
    assert "file_watchers" in body["modules"]
    assert body["modules"]["diagnostics"]["tenant"]["diagnostics_live_opt_in"] is False
    assert body["modules"]["diagnostics"]["effective"]["live_exec"] is False

    patched = client.patch(
        "/api/admin/live-settings",
        headers=auth_headers,
        json={
            "monitor_live_opt_in": True,
            "sp_live_opt_in": True,
            "diagnostics_live_opt_in": True,
            "itsm_automation_opt_in": True,
        },
    )
    assert patched.status_code == 200, patched.text
    out = patched.json()
    assert out["modules"]["monitoring"]["tenant"]["monitor_live_opt_in"] is True
    assert out["modules"]["portal"]["tenant"]["sp_live_opt_in"] is True
    assert out["modules"]["diagnostics"]["tenant"]["diagnostics_live_opt_in"] is True
    assert out["modules"]["itsm_automation"]["tenant"]["itsm_automation_opt_in"] is True
    # Platform masters still off → effective remains false.
    assert out["modules"]["monitoring"]["effective"]["platform_enabled"] is False
    assert out["modules"]["portal"]["effective"]["live_exec"] is False
    assert out["modules"]["diagnostics"]["effective"]["live_exec"] is False
    assert out["modules"]["itsm_automation"]["effective"]["automation"] is False


def test_unified_live_settings_rbac_matrix() -> None:
    """Only admin/owner get live:admin; viewer/member must not."""
    from app.permissions import (
        PERM_LIVE_ADMIN,
        permissions_for_role,
    )
    from app.tenancy import (
        MEMBERSHIP_ROLE_ADMIN,
        MEMBERSHIP_ROLE_MEMBER,
        MEMBERSHIP_ROLE_OWNER,
        MEMBERSHIP_ROLE_VIEWER,
    )

    assert PERM_LIVE_ADMIN not in permissions_for_role(MEMBERSHIP_ROLE_VIEWER)
    assert PERM_LIVE_ADMIN not in permissions_for_role(MEMBERSHIP_ROLE_MEMBER)
    assert PERM_LIVE_ADMIN in permissions_for_role(MEMBERSHIP_ROLE_ADMIN)
    assert PERM_LIVE_ADMIN in permissions_for_role(MEMBERSHIP_ROLE_OWNER)


@pytest.mark.usefixtures("clean_db")
def test_diagnostics_live_requires_both_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenants_service.ensure_migration_tenant()
    tenants_service.set_module_live_settings(
        MIGRATION_TENANT_ID, {"diagnostics_live_opt_in": True}
    )
    get_settings.cache_clear()
    assert (
        live_settings_service.diagnostics_live_allowed(tenant_id=MIGRATION_TENANT_ID)
        is False
    )
    monkeypatch.setenv("DIAGNOSTICS_LIVE_ENABLED", "true")
    get_settings.cache_clear()
    assert (
        live_settings_service.diagnostics_live_allowed(tenant_id=MIGRATION_TENANT_ID)
        is True
    )
    get_settings.cache_clear()


@pytest.mark.usefixtures("clean_db")
def test_diagnostics_prefer_live_fail_closed(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Seed a CI to diagnose.
    created = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Server",
            "name": "live-diag-host",
            "hostname": "127.0.0.1",
            "environment": "lab",
            "status": "active",
        },
    )
    assert created.status_code == 201, created.text
    cid = created.json()["component_id"]

    denied = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={"component_id": cid, "profile_name": "basic-health", "prefer_live": True},
    )
    assert denied.status_code == 403, denied.text

    # Open both gates → LIVE run succeeds.
    monkeypatch.setenv("DIAGNOSTICS_LIVE_ENABLED", "true")
    get_settings.cache_clear()
    tenants_service.set_module_live_settings(
        MIGRATION_TENANT_ID, {"diagnostics_live_opt_in": True}
    )
    ok = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={"component_id": cid, "profile_name": "basic-health", "prefer_live": True},
    )
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["execution_mode"] == "LIVE"
    assert any(c.get("check_id") == "live_connectivity" for c in body["checks"])

    # SIMULATED still works without prefer_live.
    sim = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={"component_id": cid, "profile_name": "basic-health"},
    )
    assert sim.status_code == 201, sim.text
    assert sim.json()["execution_mode"] == "SIMULATED"
    get_settings.cache_clear()


@pytest.mark.usefixtures("clean_db")
def test_itsm_automation_fail_closed_without_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenants_service.ensure_migration_tenant()
    get_settings.cache_clear()
    assert (
        live_settings_service.itsm_automation_allowed(tenant_id=MIGRATION_TENANT_ID)
        is False
    )
    tenants_service.set_module_live_settings(
        MIGRATION_TENANT_ID, {"itsm_automation_opt_in": True}
    )
    assert (
        live_settings_service.itsm_automation_allowed(tenant_id=MIGRATION_TENANT_ID)
        is False
    )
    monkeypatch.setenv("ITSM_AUTOMATION_ENABLED", "true")
    get_settings.cache_clear()
    assert (
        live_settings_service.itsm_automation_allowed(tenant_id=MIGRATION_TENANT_ID)
        is True
    )
    get_settings.cache_clear()


@pytest.mark.usefixtures("clean_db")
def test_legacy_module_endpoints_still_work(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    mon = client.get("/api/monitor/admin/live-settings", headers=auth_headers)
    assert mon.status_code == 200, mon.text
    portal = client.get("/api/portal/admin/live-settings", headers=auth_headers)
    assert portal.status_code == 200, portal.text
