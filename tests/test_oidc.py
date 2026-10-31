"""OIDC authentication tests with a mocked IdP."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient


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
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-oidc")
    monkeypatch.setenv("SESSION_COOKIE_NAME", "svrmon24_session")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")


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


def test_oidc_login_redirects_to_idp(oidc_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.oidc.fetch_discovery", lambda settings: _fake_discovery())
    response = oidc_client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    assert location.startswith(_fake_discovery()["authorization_endpoint"])
    qs = parse_qs(parsed.query)
    assert qs["response_type"] == ["code"]
    assert qs["client_id"] == [CLIENT_ID]
    assert qs["code_challenge_method"] == ["S256"]
    assert "code_challenge" in qs
    assert "state" in qs
    assert "nonce" in qs


def test_oidc_happy_path_callback_sets_session_and_protects_api(
    oidc_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr("app.oidc.fetch_discovery", lambda settings: _fake_discovery())

    def fake_exchange(settings, *, code: str, code_verifier: str) -> dict[str, Any]:
        assert code == "test-auth-code"
        assert code_verifier
        return {
            "access_token": "access-token",
            "id_token": "fake-id-token",
            "token_type": "Bearer",
        }

    def fake_validate(settings, id_token: str, *, nonce: str | None = None) -> dict[str, Any]:
        assert id_token == "fake-id-token"
        assert nonce  # must have been stored during /auth/login
        return {
            "sub": "user-123",
            "preferred_username": "alice",
            "email": "alice@example.com",
            "name": "Alice Example",
            "nonce": nonce,
        }

    monkeypatch.setattr("app.oidc.exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr("app.oidc.validate_id_token", fake_validate)
    # Callback imports names from app.oidc into auth_routes — patch both paths.
    monkeypatch.setattr("app.routers.auth_routes.exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr("app.routers.auth_routes.validate_id_token", fake_validate)
    monkeypatch.setattr(
        "app.routers.auth_routes.build_authorization_url",
        lambda settings, *, state, nonce, code_challenge: (
            _fake_discovery()["authorization_endpoint"]
            + f"?state={state}&nonce={nonce}&code_challenge={code_challenge}"
        ),
    )

    login = oidc_client.get("/auth/login", follow_redirects=False)
    assert login.status_code == 302
    qs = parse_qs(urlparse(login.headers["location"]).query)
    state = qs["state"][0]

    callback = oidc_client.get(
        f"/auth/callback?code=test-auth-code&state={state}",
        follow_redirects=False,
    )
    assert callback.status_code == 302
    assert callback.headers["location"] in {"/", "http://testserver/"}

    me = oidc_client.get("/api/me")
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == "alice"
    assert body["auth_method"] == "oidc"
    assert body["subject"] == "user-123"
    assert body["email"] == "alice@example.com"

    status = oidc_client.get("/api/status")
    assert status.status_code == 200

    logout = oidc_client.get("/auth/logout", follow_redirects=False)
    assert logout.status_code == 302
    # After logout, API requires auth again
    assert oidc_client.get("/api/me").status_code == 401


def test_oidc_callback_rejects_bad_state(oidc_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routers.auth_routes.build_authorization_url",
        lambda settings, *, state, nonce, code_challenge: "http://idp.test/auth",
    )
    monkeypatch.setattr("app.oidc.fetch_discovery", lambda settings: _fake_discovery())
    login = oidc_client.get("/auth/login", follow_redirects=False)
    assert login.status_code == 302
    bad = oidc_client.get("/auth/callback?code=x&state=wrong", follow_redirects=False)
    assert bad.status_code == 302
    assert "auth_error=oidc_state" in bad.headers["location"]


def test_oidc_login_redirects_when_host_mismatches_redirect_uri(monkeypatch) -> None:
    """127.0.0.1 vs localhost (or any host ≠ redirect URI) must bounce before IdP."""
    _oidc_env(monkeypatch)
    monkeypatch.setenv("OIDC_REDIRECT_URI", "http://localhost:8200/auth/callback")

    from app.config import get_settings
    from app.db import reset_client_for_tests
    from app.main import create_app
    from app.oidc import clear_discovery_cache

    get_settings.cache_clear()
    clear_discovery_cache()
    reset_client_for_tests()
    app = create_app()
    with TestClient(app) as client:
        cfg = client.get("/api/auth/config").json()
        assert cfg["host_matches_redirect"] is False
        assert "localhost" in cfg["expected_origin"]
        assert "127.0.0.1" in (cfg.get("host_hint") or "") or "localhost" in cfg["host_hint"]

        response = client.get("/auth/login", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "http://localhost:8200/auth/login"
    get_settings.cache_clear()
    clear_discovery_cache()


def test_oidc_callback_missing_state_redirects_with_guidance(
    oidc_client: TestClient,
) -> None:
    """No prior /auth/login session → friendly auth_error redirect (not raw JSON)."""
    response = oidc_client.get(
        "/auth/callback?code=orphan&state=missing",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "auth_error=oidc_state" in response.headers["location"]


def test_oidc_and_basic_coexistence(monkeypatch) -> None:
    """With both flags on, Basic still works alongside OIDC sessions."""
    _oidc_env(monkeypatch)
    monkeypatch.setenv("BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("BASIC_AUTH_USERNAME", "testuser")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "testpass")

    from app.config import get_settings
    from app.db import reset_client_for_tests
    from app.main import create_app
    from app.oidc import clear_discovery_cache

    get_settings.cache_clear()
    clear_discovery_cache()
    reset_client_for_tests()
    app = create_app()
    token = base64.b64encode(b"testuser:testpass").decode("ascii")
    with TestClient(app) as client:
        cfg = client.get("/api/auth/config").json()
        assert cfg["basic_auth_enabled"] is True
        assert cfg["oidc_enabled"] is True
        me = client.get("/api/me", headers={"Authorization": f"Basic {token}"})
        assert me.status_code == 200
        assert me.json()["auth_method"] == "basic"
        assert me.json()["username"] == "testuser"
    get_settings.cache_clear()
    clear_discovery_cache()


def test_ui_exposes_oidc_login_controls() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "js" / "cmdb.js").read_text(encoding="utf-8")
    assert 'id="btnOidcLogin"' in html
    assert 'id="oidcAuthRow"' in html
    assert 'id="basicAuthRow"' in html
    assert 'id="loginGate"' in html
    assert "is-login" in html
    assert "/api/auth/config" in js
    assert "/auth/login" in js
    assert "credentials: \"include\"" in js or "credentials: 'include'" in js
    assert "tenantSwitcher" in html  # in Settings; still not activated
    assert "auth_error" in js
    assert "host_matches_redirect" in js or "hostMismatchBanner" in html
