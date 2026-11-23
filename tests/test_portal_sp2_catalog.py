"""Service Portal SP2 — catalog seed + form validation (0.96.0)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.portal.services.seed import ACTION_KEY_ALLOWLIST, seed_catalog_specs

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_portal_sp2() -> None:
    assert __version__ == "0.96.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.96.0"' in html
    assert "portal/catalog.js?v=0.96.0" in html


def test_seed_specs_cover_all_domains() -> None:
    specs = seed_catalog_specs()
    domains = {s["domain"] for s in specs}
    assert domains == {
        "os",
        "middleware",
        "database",
        "networking",
        "cloud",
        "generic",
        "vulnerability",
        "other",
    }
    assert all(s["change_type_key"].startswith("sp.") for s in specs)
    assert all(s["action_key"] in ACTION_KEY_ALLOWLIST for s in specs)


@pytest.mark.usefixtures("clean_db")
def test_catalog_seed_list_validate(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200, seed.text
    body = seed.json()
    assert body["created"] >= 1
    assert body["total_seed"] == len(seed_catalog_specs())

    listed = client.get("/api/portal/catalog", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["total"] >= body["total_seed"]
    assert "cloud" in payload["domains"]
    assert "generic" in payload["domains"]
    assert "vulnerability" in payload["domains"]

    cloud = client.get(
        "/api/portal/catalog",
        headers=auth_headers,
        params={"domain": "cloud"},
    )
    assert cloud.status_code == 200
    assert all(i["domain"] == "cloud" for i in cloud.json()["items"])
    assert any(i["key"] == "cloud.vm.provision" for i in cloud.json()["items"])

    item = next(i for i in payload["items"] if i["key"] == "os.user.create")
    detail = client.get(
        f"/api/portal/catalog/{item['item_id']}", headers=auth_headers
    )
    assert detail.status_code == 200
    assert detail.json()["change_type_key"] == "sp.os.user.create"

    bad = client.post(
        f"/api/portal/catalog/{item['item_id']}/validate",
        headers=auth_headers,
        json={"form_values": {"username": "BAD USER", "groups": "users"}},
    )
    assert bad.status_code == 400, bad.text
    # App exception envelope uses {"error": {"message", "details"}} (not FastAPI detail).
    err_body = bad.json().get("error") or {}
    details = err_body.get("details") or bad.json().get("detail") or {}
    assert "field_errors" in details, bad.text

    good = client.post(
        f"/api/portal/catalog/{item['item_id']}/validate",
        headers=auth_headers,
        json={
            "form_values": {
                "username": "alice",
                "groups": "users",
                "create_home": True,
                "target_ci": "srv-demo-1",
            }
        },
    )
    assert good.status_code == 200, good.text
    assert good.json()["ok"] is True


@pytest.mark.usefixtures("clean_db")
def test_catalog_rejects_unknown_action_key(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/api/portal/catalog",
        headers=auth_headers,
        json={
            "key": "evil.rce",
            "title": "Evil",
            "domain": "other",
            "action_key": "evil.shell.run",
            "change_type_key": "sp.evil",
            "adapter": "other",
            "form_schema": {"version": 1, "fields": []},
        },
    )
    assert resp.status_code == 400, resp.text
    err = resp.json().get("error") or {}
    detail_text = str(
        err.get("message") or resp.json().get("detail") or resp.text
    )
    assert "allowlist" in detail_text.lower(), resp.text


def test_portal_catalog_fe_markers() -> None:
    js = Path("frontend/static/js/portal/catalog.js").read_text(encoding="utf-8")
    assert "SVRMON24PortalCatalog" in js
    assert "/api/portal/catalog" in js
    assert "change_type_key" in js
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert "portal/catalog.js" in html
