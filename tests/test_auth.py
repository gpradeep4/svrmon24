"""HTTP Basic authentication tests (feature-flag coexistence)."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient


def test_auth_config_public(client: TestClient) -> None:
    response = client.get("/api/auth/config")
    assert response.status_code == 200
    body = response.json()
    assert body["basic_auth_enabled"] is True  # suite default in conftest
    assert body["oidc_enabled"] is False
    assert body["login_path"] == "/auth/login"
    assert body["logout_path"] == "/auth/logout"


def test_protected_route_requires_auth(client: TestClient) -> None:
    response = client.get("/api/me")
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate", "").startswith("Basic")


def test_protected_route_rejects_bad_credentials(client: TestClient) -> None:
    bad = base64.b64encode(b"testuser:wrongpass").decode("ascii")
    response = client.get("/api/me", headers={"Authorization": f"Basic {bad}"})
    assert response.status_code == 401


def test_protected_route_accepts_valid_credentials(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "testuser"
    assert body["auth_method"] == "basic"


def test_api_status_requires_auth(client: TestClient) -> None:
    response = client.get("/api/status")
    assert response.status_code == 401


def test_basic_auth_disabled_rejects_basic_header(monkeypatch) -> None:
    """When BASIC_AUTH_ENABLED=false, Basic credentials must not authenticate."""
    monkeypatch.setenv("BASIC_AUTH_ENABLED", "false")
    monkeypatch.setenv("OIDC_ENABLED", "false")
    monkeypatch.setenv("BASIC_AUTH_USERNAME", "testuser")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "testpass")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")

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
        # No auth method enabled → 503 on protected routes
        response = client.get("/api/me", headers={"Authorization": f"Basic {token}"})
        assert response.status_code == 503
        cfg = client.get("/api/auth/config").json()
        assert cfg["basic_auth_enabled"] is False
        assert cfg["oidc_enabled"] is False
    get_settings.cache_clear()
    clear_discovery_cache()


def test_basic_auth_disabled_with_oidc_session_path_still_needs_session(monkeypatch) -> None:
    """Basic off + OIDC on: bare Basic header does not authenticate."""
    monkeypatch.setenv("BASIC_AUTH_ENABLED", "false")
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_ISSUER", "http://idp.test/realms/svrmon24")
    monkeypatch.setenv("OIDC_CLIENT_ID", "svrmon24-ui")
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "http://testserver/auth/callback")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret")

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
        response = client.get("/api/me", headers={"Authorization": f"Basic {token}"})
        assert response.status_code == 401
        assert "Bearer" in response.headers.get("WWW-Authenticate", "")
        cfg = client.get("/api/auth/config").json()
        assert cfg["basic_auth_enabled"] is False
        assert cfg["oidc_enabled"] is True
    get_settings.cache_clear()
    clear_discovery_cache()
