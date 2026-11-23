"""Service Portal SP0 — package, meta, RBAC stubs (0.86.0)."""

from __future__ import annotations

from app import __version__
from app.config import Settings, get_settings
from app.db import get_itsm_database, reset_client_for_tests
from app.permissions import (
    ALL_PERMISSIONS,
    PERM_SP_ADMIN,
    PERM_SP_CATALOG_READ,
    permissions_for_role,
)
from app.portal import PORTAL_COLLECT_MODES, PORTAL_DOMAINS
from app.tenancy import (
    MEMBERSHIP_ROLE_ADMIN,
    MEMBERSHIP_ROLE_MEMBER,
    MEMBERSHIP_ROLE_VIEWER,
)
from fastapi.testclient import TestClient


def test_version_bump_for_portal_sp0() -> None:
    assert __version__ == "0.86.0"


def test_portal_domains_include_cloud_and_generic() -> None:
    assert "cloud" in PORTAL_DOMAINS
    assert "generic" in PORTAL_DOMAINS
    assert "os" in PORTAL_DOMAINS
    assert PORTAL_COLLECT_MODES == ("agentless", "agent")


def test_portal_permissions_in_matrix() -> None:
    assert PERM_SP_CATALOG_READ in ALL_PERMISSIONS
    assert PERM_SP_ADMIN in ALL_PERMISSIONS
    viewer = permissions_for_role(MEMBERSHIP_ROLE_VIEWER)
    member = permissions_for_role(MEMBERSHIP_ROLE_MEMBER)
    admin = permissions_for_role(MEMBERSHIP_ROLE_ADMIN)
    assert PERM_SP_CATALOG_READ in viewer
    assert PERM_SP_CATALOG_READ in member
    assert "sp:request:create" in member
    assert PERM_SP_ADMIN in admin
    assert PERM_SP_ADMIN not in member


def test_portal_uses_itsm_database(monkeypatch) -> None:
    monkeypatch.setenv("MONGODB_ITSM_DB", "explicit-itsm-for-portal")
    get_settings.cache_clear()
    reset_client_for_tests()
    settings = Settings(_env_file=None)
    assert get_itsm_database(settings).name == "explicit-itsm-for-portal"
    reset_client_for_tests()
    get_settings.cache_clear()


def test_portal_meta_requires_auth(client: TestClient) -> None:
    response = client.get("/api/portal/meta")
    assert response.status_code in {401, 403}


def test_portal_meta_simulated_tenant_aware(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/portal/meta", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["module"] == "service_portal"
    assert body["execution_mode"] == "SIMULATED"
    assert body["live_exec"] is False
    assert body["demo_only"] is True
    assert body["collect_modes"] == ["agentless", "agent"]
    assert "cloud" in body["domains"]
    assert "generic" in body["domains"]
    assert "os" in body["domains"]
    assert body["live_gates"]["fail_closed"] is True
    assert body["live_gates"]["live_exec"] is False
    assert body["cmdb_sync"] is True
    assert body["agent_channel"] == "monitoring"
    assert "SIMULATED" in body["banner"]
    assert body["itsm_database"]
    assert body["database"] == body["itsm_database"]
    assert body["tenant_id"]
    assert "sp_catalog_items" in body["collections"]
    assert "sp_requests" in body["collections"]
    assert "sp_approval_steps" not in body["collections"]
    assert "sp_approval_policies" not in body["collections"]
