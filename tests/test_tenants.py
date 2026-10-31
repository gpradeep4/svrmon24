"""Master Phase 4 — tenant seed, memberships, dual-write, no auto platform-admin."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.tenancy import (
    MEMBERSHIP_ROLE_MEMBER,
    MIGRATION_TENANT_DISPLAY_NAME,
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
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-oidc-tenants")
    monkeypatch.setenv("SESSION_COOKIE_NAME", "svrmon24_session")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("MONGODB_DB", "svrmon24_test")


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
    sub: str = "user-123",
    username: str = "alice",
    email: str = "alice@example.com",
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
            "name": "Alice Example",
            "nonce": nonce,
            "iss": ISSUER,
            "aud": CLIENT_ID,
        }

    monkeypatch.setattr("app.oidc.exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr("app.oidc.validate_id_token", fake_validate)
    # auth_routes binds these names at import — patch both module paths.
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


def test_ensure_migration_tenant_idempotent(clean_db) -> None:
    from app.services.bootstrap import ensure_tenancy_ready
    from app.services import tenants as tenants_service

    first = ensure_tenancy_ready()
    assert first["ok"] is True
    assert first["migration_tenant_id"] == MIGRATION_TENANT_ID
    assert first["isolation_enforced"] is False

    again = tenants_service.ensure_migration_tenant()
    assert again["tenant_id"] == MIGRATION_TENANT_ID
    assert again["display_name"] == MIGRATION_TENANT_DISPLAY_NAME
    assert again["switchable"] is False

    listed = tenants_service.list_tenants()
    assert len(listed) == 1
    assert listed[0]["tenant_id"] == MIGRATION_TENANT_ID


def test_dual_write_tenant_id_on_component_create(client, auth_headers, clean_db) -> None:
    from app.tenancy import MIGRATION_TENANT_ID as TID

    response = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Server",
            "name": "tenant-dual-write-srv",
            "environment": "lab",
            "status": "active",
            "hostname": "dual-write.example",
            "os_family": "Linux",
            "os_version": "9",
        },
    )
    assert response.status_code in (200, 201), response.text
    body = response.json()
    assert body["tenant_id"] == TID
    # Still globally unique component_id
    assert body["component_id"]


def test_membership_crud_link_and_list(clean_db) -> None:
    from app.services import memberships as memberships_service
    from app.services import tenants as tenants_service
    from app.services import users as users_service

    tenants_service.ensure_migration_tenant()
    user = users_service.ensure_user_from_oidc(
        issuer=ISSUER,
        subject="mem-user-1",
        username="member1",
        email="member1@example.com",
    )
    assert user["is_platform_admin"] is False

    mem = memberships_service.ensure_membership(
        user_id=user["user_id"],
        tenant_id=MIGRATION_TENANT_ID,
        role=MEMBERSHIP_ROLE_MEMBER,
    )
    assert mem["role"] == "member"
    again = memberships_service.ensure_membership(
        user_id=user["user_id"],
        tenant_id=MIGRATION_TENANT_ID,
        role=MEMBERSHIP_ROLE_MEMBER,
    )
    assert again["membership_id"] == mem["membership_id"]

    listed = memberships_service.list_memberships_for_user(user["user_id"])
    assert len(listed) == 1
    assert listed[0]["tenant_id"] == MIGRATION_TENANT_ID


def test_oidc_login_links_user_never_auto_platform_admin(
    oidc_client: TestClient, monkeypatch, clean_db
) -> None:
    from app.db import get_database

    _complete_oidc_login(oidc_client, monkeypatch)

    me = oidc_client.get("/api/me")
    assert me.status_code == 200
    body = me.json()
    assert body["auth_method"] == "oidc"
    assert body["username"] == "alice"
    assert body["user_id"]
    assert body["is_platform_admin"] is False
    assert body["current_tenant_id"] == MIGRATION_TENANT_ID
    assert body["current_tenant_display_name"] == MIGRATION_TENANT_DISPLAY_NAME
    assert body["org_switcher_enabled"] is False
    assert body["isolation_enforced"] is False
    assert any(m["role"] == "member" for m in body.get("memberships") or [])

    # Direct DB proof: no accidental platform admin
    db = get_database()
    doc = db["users"].find_one({"user_id": body["user_id"]})
    assert doc is not None
    assert doc.get("is_platform_admin") is False

    tenants = oidc_client.get("/api/tenants/current")
    assert tenants.status_code == 200
    assert tenants.json()["tenant"]["tenant_id"] == MIGRATION_TENANT_ID
    assert tenants.json()["isolation_enforced"] is False

    mem = oidc_client.get("/api/memberships")
    assert mem.status_code == 200
    assert mem.json()["count"] >= 1
    assert mem.json()["is_platform_admin"] is False


def test_platform_admin_cli_bootstrap_only(clean_db) -> None:
    from app.services import users as users_service
    from scripts.bootstrap_platform_admin import main as bootstrap_main

    # Public OIDC-style upsert stays non-admin
    user = users_service.ensure_user_from_oidc(
        issuer=ISSUER,
        subject="ops-sub",
        username="operator",
        email="ops@example.com",
    )
    assert user["is_platform_admin"] is False

    rc = bootstrap_main(
        [
            "--username",
            "operator",
            "--email",
            "ops@example.com",
            "--oidc-issuer",
            ISSUER,
            "--oidc-subject",
            "ops-sub",
            "--tenant-role",
            "admin",
        ]
    )
    assert rc == 0
    upgraded = users_service.get_user_by_oidc(ISSUER, "ops-sub")
    assert upgraded is not None
    assert upgraded["is_platform_admin"] is True

    # Login path still does not clear or invent platform admin for a new user
    other = users_service.ensure_user_from_oidc(
        issuer=ISSUER,
        subject="public-sub",
        username="public",
        email="public@example.com",
    )
    assert other["is_platform_admin"] is False


def test_basic_auth_memberships_empty(client, auth_headers, clean_db) -> None:
    # Ensure tenant exists for /api/tenants/current
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()

    current = client.get("/api/tenants/current", headers=auth_headers)
    assert current.status_code == 200
    assert current.json()["tenant"]["tenant_id"] == MIGRATION_TENANT_ID
    assert current.json()["tenant"]["display_name"] == MIGRATION_TENANT_DISPLAY_NAME

    me = client.get("/api/me", headers=auth_headers)
    assert me.status_code == 200
    me_body = me.json()
    assert me_body["current_tenant_id"] == MIGRATION_TENANT_ID
    assert me_body["current_tenant_display_name"] == MIGRATION_TENANT_DISPLAY_NAME

    mem = client.get("/api/memberships", headers=auth_headers)
    assert mem.status_code == 200
    body = mem.json()
    assert body["count"] == 0
    assert body["user_id"] is None
    assert body["auth_method"] == "basic"


def test_ui_shows_migration_tenant_non_switchable() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    css = (root / "app" / "static" / "css" / "cmdb.css").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "js" / "cmdb.js").read_text(encoding="utf-8")
    assert "tenant-svrmon24-legacy" in html
    assert "SVRMON24 Legacy" in html
    assert 'id="tenantSwitcher"' in html
    assert "disabled" in html
    assert 'id="tenantBanner"' in html
    assert 'id="tenantDisplayName"' in html
    assert 'id="tenantIdSub"' in html
    topbar = html.split('<header class="topbar">', 1)[1].split("</header>", 1)[0]
    assert 'id="tenantBanner"' in topbar
    assert "tenantSwitcher" not in topbar
    assert "accentPicker" not in topbar
    assert "loadTenancyContext" in js
    assert "setTenantBanner" in js
    assert "current_tenant_display_name" in js
    assert "/api/tenants/current" in js
    assert "/api/memberships" in js
    assert ".tenant-banner" in css
    assert "0.13.1" in html
