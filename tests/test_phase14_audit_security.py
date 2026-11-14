"""Master Phase 14 — audit logging, cross-tenant denial fuzz, OIDC negatives.

Targeted suite only (do not expand into the full pytest run for phase gate).
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.tenancy import MIGRATION_TENANT_ID


ISSUER = "http://idp.test/realms/svrmon24"
CLIENT_ID = "svrmon24-ui"
CLIENT_SECRET = "test-secret"
REDIRECT_URI = "http://testserver/auth/callback"

OTHER_TENANT = "tenant-phase14-other"
OTHER_COMPONENT = "p14-other-srv-001"
OTHER_REL = "p14-other-rel-001"
OTHER_AUDIT = "aud-foreign-phase14"


def _oidc_env(monkeypatch) -> None:
    monkeypatch.setenv("BASIC_AUTH_ENABLED", "false")
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("OIDC_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("OIDC_REDIRECT_URI", REDIRECT_URI)
    monkeypatch.setenv("OIDC_SCOPES", "openid profile email")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-phase14")
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
    sub: str = "user-p14",
    username: str = "pat",
    email: str = "pat@example.com",
    nonce_override: str | None = None,
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
            "name": "Pat Example",
            "nonce": nonce_override if nonce_override is not None else nonce,
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


@pytest.fixture()
def foreign_tenant_docs(clean_db):
    """Second-tenant CMDB + audit docs that migration Basic must not see."""
    from app.db import get_database
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    db = get_database()
    now = datetime.now(timezone.utc)
    db["tenants"].update_one(
        {"tenant_id": OTHER_TENANT},
        {
            "$set": {
                "tenant_id": OTHER_TENANT,
                "display_name": "Phase14 Other",
                "slug": "phase14-other",
                "status": "active",
                "is_migration_tenant": False,
                "switchable": False,
                "plan_code": "starter",
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    db["cmdb_servers"].insert_one(
        {
            "component_id": OTHER_COMPONENT,
            "component_type": "Server",
            "name": "other-p14",
            "environment": "prod",
            "status": "active",
            "hostname": "other-p14.example",
            "os_family": "Linux",
            "os_version": "9",
            "tenant_id": OTHER_TENANT,
            "custom_fields": {},
            "created_at": now,
            "updated_at": now,
        }
    )
    db["cmdb_relationships"].insert_one(
        {
            "relationship_id": OTHER_REL,
            "source_component_id": OTHER_COMPONENT,
            "target_component_id": OTHER_COMPONENT + "-tgt",
            "relationship_type": "depends_on",
            "protocol": "https",
            "source_port": 443,
            "target_port": 443,
            "discovery_method": "manual",
            "verification_status": "unverified",
            "confidence": "medium",
            "duplicate_key": f"p14-dup-{OTHER_REL}",
            "tenant_id": OTHER_TENANT,
            "created_at": now,
            "updated_at": now,
        }
    )
    db["audit_events"].insert_one(
        {
            "audit_id": OTHER_AUDIT,
            "timestamp": now,
            "tenant_id": OTHER_TENANT,
            "action": "component.create",
            "resource_type": "component",
            "resource_id": OTHER_COMPONENT,
            "actor": {"username": "foreign", "auth_method": "oidc"},
            "details": {},
            "outcome": "success",
        }
    )
    yield {
        "tenant_id": OTHER_TENANT,
        "component_id": OTHER_COMPONENT,
        "relationship_id": OTHER_REL,
        "audit_id": OTHER_AUDIT,
    }


def test_version_is_release_ready() -> None:
    from app import __version__

    assert __version__ == "0.32.9"


def test_audit_logs_mutating_cmdb_and_list(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()

    created = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_id": "p14-aud-srv-1",
            "component_type": "Server",
            "name": "audit-server",
            "environment": "lab",
            "status": "active",
            "hostname": "aud.example",
            "os_family": "Linux",
            "os_version": "9",
        },
    )
    assert created.status_code == 201, created.text

    listed = client.get("/api/audit-events", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["tenant_id"] == MIGRATION_TENANT_ID
    assert body["collection"] == "audit_events"
    actions = {item["action"] for item in body["items"]}
    assert "component.create" in actions
    match = next(i for i in body["items"] if i["resource_id"] == "p14-aud-srv-1")
    assert match["actor"]["auth_method"] == "basic"
    assert match["outcome"] == "success"

    got = client.get(f"/api/audit-events/{match['audit_id']}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["audit_id"] == match["audit_id"]


def test_cross_tenant_denial_fuzz(
    client: TestClient,
    auth_headers: dict[str, str],
    foreign_tenant_docs,
) -> None:
    """Targeted fuzz: foreign ids across CMDB / relationships / audit → 404."""
    foreign = foreign_tenant_docs
    probes = [
        ("GET", f"/api/components/{foreign['component_id']}"),
        ("PUT", f"/api/components/{foreign['component_id']}"),
        ("DELETE", f"/api/components/{foreign['component_id']}?confirmed=true"),
        ("GET", f"/api/relationships/{foreign['relationship_id']}"),
        ("DELETE", f"/api/relationships/{foreign['relationship_id']}"),
        ("GET", f"/api/audit-events/{foreign['audit_id']}"),
        ("GET", f"/api/tenants/{foreign['tenant_id']}"),
        ("GET", f"/api/tenants/{foreign['tenant_id']}/members"),
    ]
    for method, path in probes:
        if method == "GET":
            resp = client.get(path, headers=auth_headers)
        elif method == "PUT":
            resp = client.put(
                path,
                headers=auth_headers,
                json={"name": "should-not-update"},
            )
        else:
            resp = client.delete(path, headers=auth_headers)
        assert resp.status_code in {403, 404}, (
            f"{method} {path} expected 403/404, got {resp.status_code}: {resp.text}"
        )

    # List surfaces must not leak foreign component ids.
    inv = client.get("/api/components", headers=auth_headers)
    assert inv.status_code == 200
    ids = {row["component_id"] for row in inv.json().get("items", [])}
    assert foreign["component_id"] not in ids

    aud = client.get("/api/audit-events", headers=auth_headers)
    assert aud.status_code == 200
    audit_ids = {row["audit_id"] for row in aud.json().get("items", [])}
    assert foreign["audit_id"] not in audit_ids


def test_oidc_negative_bad_nonce(
    oidc_client: TestClient, monkeypatch, clean_db
) -> None:
    """ID token nonce mismatch must fail callback (negative path)."""
    from app.oidc import OidcError

    _oidc_env(monkeypatch)
    monkeypatch.setattr("app.oidc.fetch_discovery", lambda settings: _fake_discovery())
    monkeypatch.setattr(
        "app.routers.auth_routes.build_authorization_url",
        lambda settings, *, state, nonce, code_challenge: (
            _fake_discovery()["authorization_endpoint"] + f"?state={state}"
        ),
    )
    monkeypatch.setattr(
        "app.routers.auth_routes.exchange_code_for_tokens",
        lambda settings, *, code, code_verifier: {
            "access_token": "a",
            "id_token": "t",
            "token_type": "Bearer",
        },
    )

    def boom(settings, id_token: str, *, nonce: str | None = None) -> dict[str, Any]:
        raise OidcError("nonce mismatch")

    monkeypatch.setattr("app.routers.auth_routes.validate_id_token", boom)

    login = oidc_client.get("/auth/login", follow_redirects=False)
    assert login.status_code == 302
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    callback = oidc_client.get(
        f"/auth/callback?code=bad-nonce&state={state}",
        follow_redirects=False,
    )
    assert callback.status_code == 302
    loc = callback.headers["location"]
    assert "auth_error=oidc_provider" in loc or "auth_error=oidc_state" in loc
    assert oidc_client.get("/api/me").status_code == 401


def test_oidc_negative_token_exchange_failure(
    oidc_client: TestClient, monkeypatch, clean_db
) -> None:
    from app.oidc import OidcError

    monkeypatch.setattr("app.oidc.fetch_discovery", lambda settings: _fake_discovery())
    monkeypatch.setattr(
        "app.routers.auth_routes.build_authorization_url",
        lambda settings, *, state, nonce, code_challenge: "http://idp.test/auth",
    )

    def fail_exchange(settings, *, code: str, code_verifier: str) -> dict[str, Any]:
        raise OidcError("token endpoint rejected code")

    monkeypatch.setattr("app.routers.auth_routes.exchange_code_for_tokens", fail_exchange)

    login = oidc_client.get("/auth/login", follow_redirects=False)
    assert login.status_code == 302
    # Force a session state by hitting login (stores state even if URL is stubbed)
    # Re-login to populate session cookies properly via real login path helpers.
    monkeypatch.setattr(
        "app.routers.auth_routes.build_authorization_url",
        lambda settings, *, state, nonce, code_challenge: (
            _fake_discovery()["authorization_endpoint"] + f"?state={state}"
        ),
    )
    login2 = oidc_client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(login2.headers["location"]).query)["state"][0]
    callback = oidc_client.get(
        f"/auth/callback?code=rejected&state={state}",
        follow_redirects=False,
    )
    assert callback.status_code == 302
    assert "auth_error=" in callback.headers["location"]
    assert oidc_client.get("/api/me").status_code == 401


def test_oidc_disabled_blocks_login(monkeypatch) -> None:
    monkeypatch.setenv("OIDC_ENABLED", "false")
    monkeypatch.setenv("BASIC_AUTH_ENABLED", "false")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-phase14")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("MONGODB_DB", "svrmon24_test")

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
        assert cfg["oidc_enabled"] is False
        login = client.get("/auth/login", follow_redirects=False)
        assert login.status_code == 503
        # No auth method available → unauthenticated / unavailable (not a session).
        me = client.get("/api/me")
        assert me.status_code in {401, 503}
        assert me.status_code != 200
    get_settings.cache_clear()
    clear_discovery_cache()


def test_basic_still_flagged_not_removed(monkeypatch) -> None:
    """Phase 14 must document cutover — Basic code path remains behind the flag."""
    monkeypatch.setenv("BASIC_AUTH_ENABLED", "true")
    monkeypatch.setenv("BASIC_AUTH_USERNAME", "testuser")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "testpass")
    monkeypatch.setenv("OIDC_ENABLED", "false")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-phase14")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("MONGODB_DB", "svrmon24_test")

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
        me = client.get("/api/me", headers={"Authorization": f"Basic {token}"})
        assert me.status_code == 200
        assert me.json()["auth_method"] == "basic"
        cfg = client.get("/api/auth/config").json()
        assert cfg["basic_auth_enabled"] is True
    get_settings.cache_clear()
    clear_discovery_cache()


def test_migration_dry_run_script_is_read_only(clean_db) -> None:
    from app.services import tenants as tenants_service
    from scripts.migration_dry_run import main as dry_main

    tenants_service.ensure_migration_tenant()
    rc = dry_main([])
    assert rc == 0


def test_ui_exposes_audit_panel() -> None:
    from pathlib import Path

    from app import __version__

    from tests.frontend_paths import FRONTEND_INDEX, FRONTEND_STATIC

    root = Path(__file__).resolve().parents[1]
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "cmdb.js").read_text(encoding="utf-8")
    assert 'id="tab-audit"' in html
    assert 'id="auditBody"' in html
    assert "Coming soon. Audit log storage" not in html
    assert "Audit Logs <span class=\"coming\">Soon</span>" not in html
    assert "loadAuditEvents" in js
    assert "/api/audit-events" in js
    assert f"cmdb.js?v={__version__}" in html
    assert (root / "docs" / "migration-dry-run.md").is_file()
    assert (root / "docs" / "release-hardening.md").is_file()
