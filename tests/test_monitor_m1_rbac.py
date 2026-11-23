"""Monitoring M1 — RBAC (monitor:*) + plan entitlement limits (0.64.0)."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import __version__
from app.auth import AuthUser
from app.permissions import (
    ALL_PERMISSIONS,
    PERM_DIAGNOSTICS_READ,
    PERM_DIAGNOSTICS_RUN,
    PERM_FILE_MONITORING_READ,
    PERM_MONITOR_ADMIN,
    PERM_MONITOR_ALERTS_READ,
    PERM_MONITOR_ALERTS_WRITE,
    PERM_MONITOR_DASHBOARD_READ,
    PERM_MONITOR_FILES_READ,
    PERM_MONITOR_LOGS_READ,
    PERM_MONITOR_LOGS_WRITE,
    PERM_MONITOR_TARGETS_READ,
    PERM_MONITOR_TARGETS_WRITE,
    assert_permission,
    permissions_for_role,
)
from app.services import entitlements as entitlements_service
from app.tenancy import (
    MEMBERSHIP_ROLE_ADMIN,
    MEMBERSHIP_ROLE_MEMBER,
    MEMBERSHIP_ROLE_OWNER,
    MEMBERSHIP_ROLE_VIEWER,
    MIGRATION_TENANT_ID,
)
from app.tenant_context import TenantContext


ISSUER = "http://idp.test/realms/svrmon24"
CLIENT_ID = "svrmon24-ui"
CLIENT_SECRET = "test-secret"
REDIRECT_URI = "http://testserver/auth/callback"


def test_version_bump_for_monitor_m1() -> None:
    assert __version__ == "0.94.0"


def test_monitor_permissions_in_catalog() -> None:
    expected = {
        PERM_MONITOR_DASHBOARD_READ,
        PERM_MONITOR_TARGETS_READ,
        PERM_MONITOR_TARGETS_WRITE,
        PERM_MONITOR_LOGS_READ,
        PERM_MONITOR_LOGS_WRITE,
        PERM_MONITOR_FILES_READ,
        PERM_MONITOR_ALERTS_READ,
        PERM_MONITOR_ALERTS_WRITE,
        PERM_MONITOR_ADMIN,
    }
    assert expected.issubset(set(ALL_PERMISSIONS))
    # Compat aliases remain during transition.
    assert PERM_FILE_MONITORING_READ in ALL_PERMISSIONS
    assert PERM_DIAGNOSTICS_READ in ALL_PERMISSIONS
    assert PERM_DIAGNOSTICS_RUN in ALL_PERMISSIONS


def test_role_grants_for_monitor() -> None:
    viewer = permissions_for_role(MEMBERSHIP_ROLE_VIEWER)
    member = permissions_for_role(MEMBERSHIP_ROLE_MEMBER)
    admin = permissions_for_role(MEMBERSHIP_ROLE_ADMIN)
    owner = permissions_for_role(MEMBERSHIP_ROLE_OWNER)

    for perm in (
        PERM_MONITOR_DASHBOARD_READ,
        PERM_MONITOR_TARGETS_READ,
        PERM_MONITOR_LOGS_READ,
        PERM_MONITOR_FILES_READ,
        PERM_MONITOR_ALERTS_READ,
        PERM_FILE_MONITORING_READ,
    ):
        assert perm in viewer

    assert PERM_MONITOR_TARGETS_WRITE not in viewer
    assert PERM_MONITOR_LOGS_WRITE not in viewer
    assert PERM_MONITOR_ALERTS_WRITE not in viewer
    assert PERM_MONITOR_ADMIN not in viewer

    assert PERM_MONITOR_TARGETS_WRITE in member
    assert PERM_MONITOR_LOGS_WRITE in member
    assert PERM_MONITOR_ALERTS_WRITE in member
    assert PERM_MONITOR_ADMIN not in member

    assert PERM_MONITOR_ADMIN in admin
    assert PERM_MONITOR_ADMIN in owner
    assert PERM_MONITOR_TARGETS_WRITE in admin
    assert PERM_MONITOR_ALERTS_WRITE in owner


def test_member_denied_monitor_admin_permission() -> None:
    tenant = TenantContext(
        tenant_id=MIGRATION_TENANT_ID,
        auth_user=AuthUser(
            username="member-user",
            auth_method="oidc",
            subject="member-sub",
            email="member@example.com",
        ),
        user_id="user-member",
        membership_role=MEMBERSHIP_ROLE_MEMBER,
        is_platform_admin=False,
    )
    with pytest.raises(HTTPException) as exc:
        assert_permission(tenant, PERM_MONITOR_ADMIN)
    assert exc.value.status_code == 403
    assert PERM_MONITOR_ADMIN in str(exc.value.detail)


def test_monitor_plan_limits_in_catalog() -> None:
    plans = {p["plan_code"]: p for p in entitlements_service.list_plans()}
    starter = plans["starter"]["limits"]
    standard = plans["standard"]["limits"]
    unlimited = plans["legacy_unlimited"]["limits"]

    assert starter["monitor_targets"] == 50
    assert starter["metric_samples_retained"] == 10_000
    assert starter["log_events_retained"] == 20_000
    assert starter["file_watches"] == 20
    assert starter["alert_rules"] == 10
    assert starter["monitor_simulate_ticks_per_day"] == 50

    assert standard["monitor_targets"] == 500
    assert standard["metric_samples_retained"] == 200_000
    assert standard["log_events_retained"] == 500_000
    assert standard["file_watches"] == 200
    assert standard["alert_rules"] == 100
    assert standard["monitor_simulate_ticks_per_day"] == 500

    for key in (
        "monitor_targets",
        "metric_samples_retained",
        "log_events_retained",
        "file_watches",
        "alert_rules",
        "monitor_simulate_ticks_per_day",
    ):
        assert unlimited[key] is None


def test_monitor_entitlement_helpers_unlimited_default(clean_db) -> None:
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    tid = MIGRATION_TENANT_ID
    assert entitlements_service.monitor_target_limit(tid) is None
    assert entitlements_service.metric_samples_retained_limit(tid) is None
    assert entitlements_service.log_events_retained_limit(tid) is None
    assert entitlements_service.file_watches_limit(tid) is None
    assert entitlements_service.alert_rules_limit(tid) is None
    assert entitlements_service.monitor_simulate_ticks_per_day_limit(tid) is None


def test_monitor_permissions_listed_for_roles_ui(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    resp = client.get("/api/permissions", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    keys = {p["permission"] for p in body["permissions"]}
    for perm in (
        PERM_MONITOR_DASHBOARD_READ,
        PERM_MONITOR_TARGETS_READ,
        PERM_MONITOR_TARGETS_WRITE,
        PERM_MONITOR_LOGS_READ,
        PERM_MONITOR_LOGS_WRITE,
        PERM_MONITOR_FILES_READ,
        PERM_MONITOR_ALERTS_READ,
        PERM_MONITOR_ALERTS_WRITE,
        PERM_MONITOR_ADMIN,
        PERM_FILE_MONITORING_READ,
    ):
        assert perm in keys
    assert PERM_MONITOR_DASHBOARD_READ in body["matrix"]["viewer"]
    assert PERM_MONITOR_TARGETS_WRITE in body["matrix"]["member"]
    assert PERM_MONITOR_ADMIN in body["matrix"]["admin"]
    assert PERM_MONITOR_ADMIN not in body["matrix"]["member"]
    assert PERM_MONITOR_DASHBOARD_READ in body["current"]["permissions"]


def test_monitor_meta_requires_dashboard_read(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/monitor/meta", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["live_probes"] is False
    assert body["collect_modes"] == ["agentless", "agent"]
    assert "linux" in body["os_families"]
    assert "switch" in body["network_target_kinds"]
    assert "server" in body["domains"]


def _oidc_env(monkeypatch) -> None:
    monkeypatch.setenv("BASIC_AUTH_ENABLED", "false")
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("OIDC_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("OIDC_REDIRECT_URI", REDIRECT_URI)
    monkeypatch.setenv("OIDC_SCOPES", "openid profile email")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-monitor-m1")
    monkeypatch.setenv("SESSION_COOKIE_NAME", "svrmon24_session")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("MONGODB_DB", "svrmon24_test")
    monkeypatch.setenv("OLLAMA_ENABLED", "false")


@pytest.fixture()
def oidc_client(monkeypatch) -> TestClient:
    _oidc_env(monkeypatch)

    from app.config import get_settings
    from app.db import reset_client_for_tests
    from app.main import create_app
    from app.oidc import clear_discovery_cache

    get_settings.cache_clear()
    clear_discovery_cache()
    reset_client_for_tests()
    app = create_app()
    with TestClient(app) as client:
        yield client
    reset_client_for_tests()
    get_settings.cache_clear()
    clear_discovery_cache()


def _fake_discovery() -> dict[str, Any]:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
        "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
        "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
        "end_session_endpoint": f"{ISSUER}/protocol/openid-connect/logout",
    }


def _complete_oidc_login(
    client: TestClient,
    monkeypatch,
    *,
    sub: str,
    username: str,
    email: str,
) -> None:
    monkeypatch.setattr("app.oidc.fetch_discovery", lambda settings: _fake_discovery())

    def fake_exchange(settings, *, code: str, code_verifier: str) -> dict[str, Any]:
        return {
            "access_token": "access-token",
            "id_token": "fake-id-token",
            "token_type": "Bearer",
        }

    def fake_validate(settings, id_token: str, *, nonce: str | None = None) -> dict[str, Any]:
        return {
            "sub": sub,
            "preferred_username": username,
            "email": email,
            "name": username.title(),
            "nonce": nonce,
            "iss": ISSUER,
            "aud": CLIENT_ID,
        }

    monkeypatch.setattr("app.oidc.exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr("app.oidc.validate_id_token", fake_validate)
    monkeypatch.setattr("app.routers.auth_routes.exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr("app.routers.auth_routes.validate_id_token", fake_validate)
    monkeypatch.setattr(
        "app.routers.auth_routes.build_authorization_url",
        lambda settings, *, state, nonce, code_challenge: (
            _fake_discovery()["authorization_endpoint"]
            + f"?state={state}&nonce={nonce}&code_challenge={code_challenge}"
        ),
    )

    login = client.get("/auth/login", follow_redirects=False)
    assert login.status_code == 302
    qs = parse_qs(urlparse(login.headers["location"]).query)
    state = qs["state"][0]
    callback = client.get(
        f"/auth/callback?code=test-auth-code&state={state}",
        follow_redirects=False,
    )
    assert callback.status_code == 302
    assert "signed_in=1" in callback.headers["location"]


def _set_role(user_id: str, role: str) -> None:
    from app.services import memberships as memberships_service

    mem = memberships_service.get_membership_for_user_tenant(
        user_id, MIGRATION_TENANT_ID
    )
    assert mem is not None
    memberships_service.update_membership_role(
        membership_id=mem["membership_id"],
        role=role,
    )


def _clear_platform_admin(user_id: str) -> None:
    from app.db import get_database

    get_database()["users"].update_one(
        {"user_id": user_id},
        {"$set": {"is_platform_admin": False, "platform_admin_source": None}},
    )


def test_viewer_can_read_monitor_meta(oidc_client: TestClient, monkeypatch, clean_db) -> None:
    from app.services import tenants as tenants_service
    from app.services import users as users_service

    tenants_service.ensure_migration_tenant()
    _complete_oidc_login(
        oidc_client,
        monkeypatch,
        sub="monitor-viewer-sub",
        username="monviewer",
        email="monviewer@example.com",
    )
    user = users_service.get_user_by_oidc(ISSUER, "monitor-viewer-sub")
    assert user is not None
    _clear_platform_admin(user["user_id"])
    _set_role(user["user_id"], MEMBERSHIP_ROLE_VIEWER)

    perms = oidc_client.get("/api/permissions")
    assert perms.status_code == 200
    current = perms.json()["current"]
    assert current["membership_role"] == MEMBERSHIP_ROLE_VIEWER
    assert PERM_MONITOR_DASHBOARD_READ in current["permissions"]
    assert PERM_MONITOR_ADMIN not in current["permissions"]

    meta = oidc_client.get("/api/monitor/meta")
    assert meta.status_code == 200, meta.text
    body = meta.json()
    assert body["module"] == "monitoring"
    assert body["live_probes"] is False
    assert body["collect_modes"] == ["agentless", "agent"]
