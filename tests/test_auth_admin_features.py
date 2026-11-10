"""Targeted tests for first platform admin, invites, custom roles, OIDC settings."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.tenancy import MIGRATION_TENANT_ID

ISSUER = "http://idp.test/realms/svrmon24"
CLIENT_ID = "svrmon24-ui"


def _oidc_env(monkeypatch) -> None:
    monkeypatch.setenv("BASIC_AUTH_ENABLED", "false")
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", "svrmon24-ui")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "http://testserver/auth/callback")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-auth-admin")


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
    }


def _complete_oidc_login(
    client: TestClient,
    monkeypatch,
    *,
    sub: str,
    username: str,
    email: str | None = None,
) -> None:
    monkeypatch.setattr("app.oidc.fetch_discovery", lambda settings: _fake_discovery())
    email = email or f"{username}@example.com"

    def fake_exchange(settings, *, code: str, code_verifier: str) -> dict[str, Any]:
        return {"id_token": "fake-id-token"}

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
            _fake_discovery()["authorization_endpoint"] + f"?state={state}"
        ),
    )

    login = client.get("/auth/login", follow_redirects=False)
    assert login.status_code == 302
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    callback = client.get(
        f"/auth/callback?code=test-code&state={state}",
        follow_redirects=False,
    )
    assert callback.status_code == 302


def test_first_oidc_user_becomes_platform_admin(oidc_client, monkeypatch, clean_db) -> None:
    _complete_oidc_login(oidc_client, monkeypatch, sub="first-sub", username="firstuser")
    me = oidc_client.get("/api/me").json()
    assert me["is_platform_admin"] is True

    oidc_client.get("/auth/logout", follow_redirects=False)
    _complete_oidc_login(oidc_client, monkeypatch, sub="second-sub", username="seconduser")
    me2 = oidc_client.get("/api/me").json()
    assert me2["is_platform_admin"] is False


def test_org_invite_accept_flow(oidc_client, monkeypatch, clean_db) -> None:
    from app.services import users as users_service

    _complete_oidc_login(oidc_client, monkeypatch, sub="admin-sub", username="admin")
    admin = users_service.get_user_by_oidc(ISSUER, "admin-sub")
    assert admin and admin["is_platform_admin"]

    create = oidc_client.post(
        f"/api/tenants/{MIGRATION_TENANT_ID}/invites",
        json={
            "invitee_email": "invitee@example.com",
            "invitee_username": "invitee",
            "role": "viewer",
        },
    )
    assert create.status_code == 201, create.text
    token = create.json()["invite"]["token"]

    oidc_client.get("/auth/logout", follow_redirects=False)
    _complete_oidc_login(
        oidc_client,
        monkeypatch,
        sub="invitee-sub",
        username="invitee",
        email="invitee@example.com",
    )
    accept = oidc_client.post("/api/invites/accept", json={"token": token})
    assert accept.status_code == 200, accept.text
    assert accept.json()["membership"]["role"] == "viewer"


def test_custom_role_permissions(oidc_client, monkeypatch, clean_db) -> None:
    from app.permissions import permissions_for_role

    _complete_oidc_login(oidc_client, monkeypatch, sub="owner-sub", username="owner")

    created = oidc_client.post(
        f"/api/tenants/{MIGRATION_TENANT_ID}/custom-roles",
        json={
            "role_key": "cmdb_editor",
            "display_name": "CMDB Editor",
            "permissions": ["cmdb:read", "cmdb:write", "relationships:read"],
        },
    )
    assert created.status_code == 201, created.text
    membership_role = created.json()["custom_role"]["membership_role"]
    perms = permissions_for_role(membership_role, tenant_id=MIGRATION_TENANT_ID)
    assert "cmdb:write" in perms
    assert "users:admin" not in perms


def test_platform_oidc_settings_no_secret_in_response(oidc_client, monkeypatch, clean_db) -> None:
    _complete_oidc_login(oidc_client, monkeypatch, sub="plat-sub", username="platops")

    put = oidc_client.put(
        "/api/platform/oidc-settings",
        json={
            "oidc_enabled": True,
            "issuer": "https://idp.example.com/realms/acme",
            "client_id": "acme-ui",
            "redirect_uri": "http://localhost:8200/auth/callback",
            "client_secret_env_ref": "OIDC_CLIENT_SECRET",
            "active": True,
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["issuer"] == "https://idp.example.com/realms/acme"
    assert "client_secret" not in body
    assert body["client_secret_env_ref"] == "OIDC_CLIENT_SECRET"
