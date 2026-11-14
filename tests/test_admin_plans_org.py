"""Master Phase 13 — Admin / plans / org UX (new functional tests only)."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.tenancy import (
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
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-phase13")
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


def test_org_switcher_flag_enabled() -> None:
    from app.tenancy import ORG_SWITCHER_ENABLED

    assert ORG_SWITCHER_ENABLED is True


def test_plan_catalog_and_assign(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.services import entitlements as entitlements_service
    from app.services import tenants as tenants_service
    from scripts.assign_tenant_plan import main as assign_main

    tenants_service.ensure_migration_tenant()
    catalog = entitlements_service.list_plans()
    codes = {p["plan_code"] for p in catalog}
    assert "legacy_unlimited" in codes
    assert "starter" in codes
    assert "standard" in codes

    plans = client.get("/api/entitlements/plans", headers=auth_headers)
    assert plans.status_code == 200
    body = plans.json()
    assert body["billing_enabled"] is False
    assert body["payment_provider"] is None
    assert body["count"] >= 3

    rc = assign_main(
        ["--tenant-id", MIGRATION_TENANT_ID, "--plan-code", "starter"]
    )
    assert rc == 0

    ents = client.get("/api/entitlements", headers=auth_headers)
    assert ents.status_code == 200
    payload = ents.json()
    assert payload["plan_code"] == "starter"
    assert payload["limits"]["relationships"] == 50
    assert payload["limits"]["max_ollama_analyses"] == 5
    assert payload["billing_enabled"] is False

    # Restore unlimited for other tests sharing DB cleanup.
    assert (
        assign_main(
            ["--tenant-id", MIGRATION_TENANT_ID, "--plan-code", "legacy_unlimited"]
        )
        == 0
    )


def test_platform_admin_bootstrap_with_first_oidc_user(
    oidc_client: TestClient, monkeypatch, clean_db
) -> None:
    from app.services import users as users_service
    from scripts.bootstrap_platform_admin import main as bootstrap_main

    _complete_oidc_login(oidc_client, monkeypatch)
    me = oidc_client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["is_platform_admin"] is True
    assert me.json()["org_switcher_enabled"] is True

    rc = bootstrap_main(
        [
            "--username",
            "alice",
            "--email",
            "alice@example.com",
            "--oidc-issuer",
            ISSUER,
            "--oidc-subject",
            "user-123",
            "--tenant-role",
            "admin",
        ]
    )
    assert rc == 0
    upgraded = users_service.get_user_by_oidc(ISSUER, "user-123")
    assert upgraded is not None
    assert upgraded["is_platform_admin"] is True

    # Fresh public registrant still non-admin
    other = users_service.ensure_user_from_oidc(
        issuer=ISSUER,
        subject="public-phase13",
        username="public13",
        email="public13@example.com",
    )
    assert other["is_platform_admin"] is False


def test_org_switch_multi_membership(
    oidc_client: TestClient, monkeypatch, clean_db
) -> None:
    from app.services import memberships as memberships_service
    from app.services import tenants as tenants_service
    from app.services import users as users_service
    from scripts.bootstrap_platform_admin import main as bootstrap_main
    from scripts.create_tenant import main as create_main

    _complete_oidc_login(oidc_client, monkeypatch)
    me = oidc_client.get("/api/me").json()
    user_id = me["user_id"]
    assert user_id

    # Promote to platform admin + create second org with membership
    assert (
        bootstrap_main(
            [
                "--username",
                "alice",
                "--email",
                "alice@example.com",
                "--oidc-issuer",
                ISSUER,
                "--oidc-subject",
                "user-123",
            ]
        )
        == 0
    )
    assert (
        create_main(
            [
                "--display-name",
                "Acme Corp",
                "--tenant-id",
                "tenant-acme-phase13",
                "--plan-code",
                "starter",
                "--admin-user-id",
                user_id,
            ]
        )
        == 0
    )

    listed = oidc_client.get("/api/tenants")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["org_switcher_enabled"] is True
    assert payload["switchable_for_user"] is True
    ids = {t["tenant_id"] for t in payload["items"]}
    assert MIGRATION_TENANT_ID in ids
    assert "tenant-acme-phase13" in ids

    switched = oidc_client.post(
        "/api/tenants/switch", json={"tenant_id": "tenant-acme-phase13"}
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["tenant"]["tenant_id"] == "tenant-acme-phase13"

    current = oidc_client.get("/api/tenants/current")
    assert current.status_code == 200
    assert current.json()["tenant"]["tenant_id"] == "tenant-acme-phase13"

    ents = oidc_client.get("/api/entitlements")
    assert ents.status_code == 200
    assert ents.json()["plan_code"] == "starter"
    assert ents.json()["tenant_id"] == "tenant-acme-phase13"

    # Isolation: components created under Acme are stamped with Acme tenant_id
    created = oidc_client.post(
        "/api/components",
        json={
            "component_type": "Server",
            "name": "acme-srv-1",
            "environment": "lab",
            "status": "active",
            "hostname": "acme.example",
            "os_family": "Linux",
            "os_version": "9",
        },
    )
    assert created.status_code in (200, 201), created.text
    assert created.json()["tenant_id"] == "tenant-acme-phase13"

    # Switch back to migration tenant — Acme component must not appear
    back = oidc_client.post(
        "/api/tenants/switch", json={"tenant_id": MIGRATION_TENANT_ID}
    )
    assert back.status_code == 200
    inv = oidc_client.get("/api/components?search=acme-srv-1")
    assert inv.status_code == 200
    assert inv.json().get("total", 0) == 0

    # Non-member cannot switch to a foreign tenant
    foreign = tenants_service.create_tenant(
        display_name="Other Org",
        tenant_id="tenant-other-phase13",
        plan_code="standard",
    )
    assert foreign["tenant_id"] == "tenant-other-phase13"
    denied = oidc_client.post(
        "/api/tenants/switch", json={"tenant_id": "tenant-other-phase13"}
    )
    assert denied.status_code == 403

    # Members list for current org (alice is tenant admin via bootstrap)
    members = oidc_client.get(f"/api/tenants/{MIGRATION_TENANT_ID}/members")
    assert members.status_code == 200
    assert members.json()["count"] >= 1
    assert any(m["user_id"] == user_id for m in members.json()["items"])

    # Sanity: memberships service still lists both orgs
    mems = memberships_service.list_memberships_for_user(user_id)
    assert len(mems) >= 2
    user = users_service.get_user(user_id)
    assert user is not None
    assert user["is_platform_admin"] is True


def test_basic_auth_cannot_switch(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    tenants_service.create_tenant(
        display_name="Should Not Switch",
        tenant_id="tenant-no-basic-switch",
        plan_code="starter",
    )

    listed = client.get("/api/tenants", headers=auth_headers)
    assert listed.status_code == 200
    body = listed.json()
    assert body["switchable_for_user"] is False
    assert body["count"] == 1
    assert body["items"][0]["tenant_id"] == MIGRATION_TENANT_ID

    denied = client.post(
        "/api/tenants/switch",
        headers=auth_headers,
        json={"tenant_id": "tenant-no-basic-switch"},
    )
    assert denied.status_code == 403


def test_set_plan_api_requires_platform_admin(
    oidc_client: TestClient, monkeypatch, clean_db
) -> None:
    _complete_oidc_login(
        oidc_client, monkeypatch, sub="user-123", username="alice"
    )

    oidc_client.get("/auth/logout", follow_redirects=False)
    _complete_oidc_login(
        oidc_client, monkeypatch, sub="user-456", username="bob", email="bob@example.com"
    )

    # Regular member cannot assign plans
    denied = oidc_client.put(
        f"/api/tenants/{MIGRATION_TENANT_ID}/plan",
        json={"plan_code": "starter"},
    )
    assert denied.status_code == 403

    oidc_client.get("/auth/logout", follow_redirects=False)
    _complete_oidc_login(
        oidc_client, monkeypatch, sub="user-123", username="alice"
    )

    me = oidc_client.get("/api/me")
    assert me.json()["is_platform_admin"] is True

    ok = oidc_client.put(
        f"/api/tenants/{MIGRATION_TENANT_ID}/plan",
        json={"plan_code": "standard"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["tenant"]["plan_code"] == "standard"
    assert ok.json()["billing_enabled"] is False
    assert ok.json()["plan"]["limits"]["max_diagnostic_runs"] == 200


def test_ui_markers_phase13() -> None:
    from pathlib import Path

    from app import __version__

    from tests.frontend_paths import FRONTEND_INDEX, FRONTEND_STATIC

    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    js = (FRONTEND_STATIC / "js" / "cmdb.js").read_text(encoding="utf-8")

    assert __version__ == "0.32.12"
    assert __version__ in html
    assert 'id="tenantSwitcher"' in html
    assert "Not switchable — no tenant isolation yet" not in html
    assert 'id="myMembershipsBody"' in html
    assert 'id="tenantMembersBody"' in html
    assert 'id="plansCatalogBody"' in html
    assert 'id="platformAdminStatus"' in html
    assert "/api/tenants/switch" in js
    assert "switchable_for_user" in js
    assert "loadPlansCatalog" in js
    assert "switchOrganization" in js
    assert MIGRATION_TENANT_DISPLAY_NAME in html
