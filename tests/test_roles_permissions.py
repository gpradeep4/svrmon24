"""RBAC — tenant roles and permissions (new functional tests only)."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.permissions import (
    ALL_PERMISSIONS,
    PERM_AUDIT_READ,
    PERM_CMDB_WRITE,
    PERM_CONFIG_WRITE,
    PERM_DIAGNOSTICS_RUN,
    PERM_PLANS_ADMIN,
    PERM_RELATIONSHIPS_WRITE,
    PERM_USERS_ADMIN,
    PERM_USERS_READ,
    permissions_for_role,
)
from app.tenancy import (
    MEMBERSHIP_ROLE_ADMIN,
    MEMBERSHIP_ROLE_MEMBER,
    MEMBERSHIP_ROLE_OWNER,
    MEMBERSHIP_ROLE_VIEWER,
    MIGRATION_TENANT_ID,
)


ISSUER = "http://idp.test/realms/svrmon24"
CLIENT_ID = "svrmon24-ui"
CLIENT_SECRET = "test-secret"
REDIRECT_URI = "http://testserver/auth/callback"


def _oidc_env(monkeypatch) -> None:
    monkeypatch.setenv("BASIC_AUTH_ENABLED", "false")
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("OIDC_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("OIDC_REDIRECT_URI", REDIRECT_URI)
    monkeypatch.setenv("OIDC_SCOPES", "openid profile email")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-rbac")
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


def _set_role(user_id: str, role: str) -> dict[str, Any]:
    from app.services import memberships as memberships_service

    mem = memberships_service.get_membership_for_user_tenant(
        user_id, MIGRATION_TENANT_ID
    )
    assert mem is not None
    return memberships_service.update_membership_role(
        membership_id=mem["membership_id"],
        role=role,
    )


def test_permission_matrix_defaults() -> None:
    viewer = permissions_for_role(MEMBERSHIP_ROLE_VIEWER)
    member = permissions_for_role(MEMBERSHIP_ROLE_MEMBER)
    admin = permissions_for_role(MEMBERSHIP_ROLE_ADMIN)
    owner = permissions_for_role(MEMBERSHIP_ROLE_OWNER)

    assert PERM_CMDB_WRITE not in viewer
    assert PERM_CMDB_WRITE in member
    assert PERM_CONFIG_WRITE not in member
    assert PERM_CONFIG_WRITE in admin
    assert PERM_USERS_ADMIN in admin
    assert PERM_USERS_READ in admin
    assert PERM_AUDIT_READ in admin
    assert "org:admin" not in admin
    assert "org:admin" in owner
    assert PERM_PLANS_ADMIN not in owner
    assert PERM_PLANS_ADMIN in ALL_PERMISSIONS


def test_permissions_catalog_and_basic_effective_admin(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    """HTTP Basic gets effective admin permissions on the migration tenant."""
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    resp = client.get("/api/permissions", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "viewer" in body["roles"]
    assert "owner" in body["roles"]
    assert body["current"]["effective_role"] == MEMBERSHIP_ROLE_ADMIN
    assert PERM_CMDB_WRITE in body["current"]["permissions"]
    assert PERM_CONFIG_WRITE in body["current"]["permissions"]
    assert PERM_AUDIT_READ in body["current"]["permissions"]
    assert PERM_PLANS_ADMIN not in body["current"]["permissions"]

    # Basic may mutate CMDB (effective admin).
    created = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_id": "rbac-basic-srv-1",
            "name": "RBAC Basic Server",
            "component_type": "Server",
            "environment": "lab",
            "status": "active",
        },
    )
    assert created.status_code == 201


def test_viewer_denied_mutations(
    oidc_client: TestClient, monkeypatch, clean_db
) -> None:
    from app.services import tenants as tenants_service
    from app.services import users as users_service

    tenants_service.ensure_migration_tenant()
    _complete_oidc_login(
        oidc_client,
        monkeypatch,
        sub="viewer-sub",
        username="viewer1",
        email="viewer1@example.com",
    )
    user = users_service.get_user_by_oidc(ISSUER, "viewer-sub")
    assert user is not None
    _set_role(user["user_id"], MEMBERSHIP_ROLE_VIEWER)

    perms = oidc_client.get("/api/permissions")
    assert perms.status_code == 200
    current = perms.json()["current"]
    assert current["membership_role"] == MEMBERSHIP_ROLE_VIEWER
    assert PERM_CMDB_WRITE not in current["permissions"]
    assert PERM_RELATIONSHIPS_WRITE not in current["permissions"]
    assert PERM_DIAGNOSTICS_RUN not in current["permissions"]
    assert PERM_CONFIG_WRITE not in current["permissions"]

    denied = oidc_client.post(
        "/api/components",
        json={
            "component_id": "rbac-viewer-blocked",
            "name": "Should Fail",
            "component_type": "Server",
            "environment": "lab",
            "status": "active",
        },
    )
    assert denied.status_code == 403
    assert "cmdb:write" in denied.json()["error"]["message"]

    # Reads still work.
    listing = oidc_client.get("/api/components")
    assert listing.status_code == 200

    audit = oidc_client.get("/api/audit-events")
    assert audit.status_code == 403


def test_member_can_write_cmdb_not_config(
    oidc_client: TestClient, monkeypatch, clean_db
) -> None:
    from app.services import tenants as tenants_service
    from app.services import users as users_service

    tenants_service.ensure_migration_tenant()
    _complete_oidc_login(
        oidc_client,
        monkeypatch,
        sub="member-sub",
        username="member1",
        email="member1@example.com",
    )
    user = users_service.get_user_by_oidc(ISSUER, "member-sub")
    assert user is not None
    # Default OIDC membership is already member; assert explicitly.
    _set_role(user["user_id"], MEMBERSHIP_ROLE_MEMBER)

    created = oidc_client.post(
        "/api/components",
        json={
            "component_id": "rbac-member-srv-1",
            "name": "Member Server",
            "component_type": "Server",
            "environment": "lab",
            "status": "active",
        },
    )
    assert created.status_code == 201

    field = oidc_client.post(
        "/api/custom-fields",
        json={
            "field_key": "rbac_member_blocked",
            "label": "Blocked",
            "field_type": "string",
            "applies_to": ["*"],
        },
    )
    assert field.status_code == 403
    assert "config:write" in field.json()["error"]["message"]

    members = oidc_client.get(f"/api/tenants/{MIGRATION_TENANT_ID}/members")
    assert members.status_code == 403


def test_admin_config_and_users_owner_org(
    oidc_client: TestClient, monkeypatch, clean_db
) -> None:
    from app.services import memberships as memberships_service
    from app.services import tenants as tenants_service
    from app.services import users as users_service

    tenants_service.ensure_migration_tenant()
    _complete_oidc_login(
        oidc_client,
        monkeypatch,
        sub="admin-sub",
        username="admin1",
        email="admin1@example.com",
    )
    admin = users_service.get_user_by_oidc(ISSUER, "admin-sub")
    assert admin is not None
    _set_role(admin["user_id"], MEMBERSHIP_ROLE_ADMIN)

    field = oidc_client.post(
        "/api/custom-fields",
        json={
            "field_key": "rbac_admin_ok",
            "label": "Admin Field",
            "field_type": "string",
            "applies_to": ["*"],
        },
    )
    assert field.status_code == 201

    audit = oidc_client.get("/api/audit-events")
    assert audit.status_code == 200

    members = oidc_client.get(f"/api/tenants/{MIGRATION_TENANT_ID}/members")
    assert members.status_code == 200

    # Admin cannot grant owner without org:admin.
    other = users_service.ensure_user_from_oidc(
        issuer=ISSUER,
        subject="invitee-sub",
        username="invitee",
        email="invitee@example.com",
        display_name="Invitee",
    )
    denied_owner = oidc_client.post(
        f"/api/tenants/{MIGRATION_TENANT_ID}/members",
        json={"user_id": other["user_id"], "role": MEMBERSHIP_ROLE_OWNER},
    )
    assert denied_owner.status_code == 403

    # Promote self to owner via service, then grant owner to another user.
    _set_role(admin["user_id"], MEMBERSHIP_ROLE_OWNER)
    granted = oidc_client.post(
        f"/api/tenants/{MIGRATION_TENANT_ID}/members",
        json={"user_id": other["user_id"], "role": MEMBERSHIP_ROLE_VIEWER},
    )
    assert granted.status_code == 201

    # Owner can assign owner.
    owner_grant = oidc_client.post(
        f"/api/tenants/{MIGRATION_TENANT_ID}/members",
        json={"user_id": other["user_id"], "role": MEMBERSHIP_ROLE_OWNER},
    )
    # ensure_membership with upgrade_role upgrades existing viewer → owner
    assert owner_grant.status_code == 201
    assert owner_grant.json()["membership"]["role"] == MEMBERSHIP_ROLE_OWNER

    # Platform-only plans:admin still denied for tenant owner.
    plan = oidc_client.put(
        f"/api/tenants/{MIGRATION_TENANT_ID}/plan",
        json={"plan_code": "starter"},
    )
    assert plan.status_code == 403

    # Role update endpoint demotion of last-but-one owner ok; protect last owner.
    mems = memberships_service.list_memberships_for_tenant(MIGRATION_TENANT_ID)
    owner_mems = [m for m in mems if m.get("role") == MEMBERSHIP_ROLE_OWNER]
    assert len(owner_mems) >= 2
    # Demote the other owner first.
    other_owner = next(
        m for m in owner_mems if m["user_id"] == other["user_id"]
    )
    demote = oidc_client.put(
        f"/api/tenants/{MIGRATION_TENANT_ID}/members/{other_owner['membership_id']}",
        json={"role": MEMBERSHIP_ROLE_MEMBER},
    )
    assert demote.status_code == 200
    # Now only one owner left — demoting self should 409.
    self_mem = next(m for m in owner_mems if m["user_id"] == admin["user_id"])
    last = oidc_client.put(
        f"/api/tenants/{MIGRATION_TENANT_ID}/members/{self_mem['membership_id']}",
        json={"role": MEMBERSHIP_ROLE_ADMIN},
    )
    assert last.status_code == 409


def test_platform_admin_cross_tenant_plans(
    oidc_client: TestClient, monkeypatch, clean_db
) -> None:
    from app.services import tenants as tenants_service
    from app.services import users as users_service

    tenants_service.ensure_migration_tenant()
    _complete_oidc_login(
        oidc_client,
        monkeypatch,
        sub="plat-sub",
        username="platadmin",
        email="platadmin@example.com",
    )
    user = users_service.get_user_by_oidc(ISSUER, "plat-sub")
    assert user is not None
    users_service.bootstrap_platform_admin(
        username="platadmin",
        email="platadmin@example.com",
        user_id=user["user_id"],
    )

    perms = oidc_client.get("/api/permissions").json()
    assert perms["current"]["is_platform_admin"] is True
    assert PERM_PLANS_ADMIN in perms["current"]["permissions"]
    assert set(ALL_PERMISSIONS).issubset(set(perms["current"]["permissions"]))

    plan = oidc_client.put(
        f"/api/tenants/{MIGRATION_TENANT_ID}/plan",
        json={"plan_code": "standard"},
    )
    assert plan.status_code == 200
    assert plan.json()["tenant"]["plan_code"] == "standard"

    current = oidc_client.get("/api/tenants/current")
    assert current.status_code == 200
    assert PERM_USERS_ADMIN in current.json()["permissions"]
