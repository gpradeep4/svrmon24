"""Service Portal SP11 — Vulnerability scan catalog + reports (0.99.12)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.portal.services.seed import ACTION_KEY_ALLOWLIST, seed_catalog_specs
from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_portal_vuln_scan() -> None:
    assert __version__ == "0.99.12"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.12"' in html
    assert "portal/vuln.js?v=0.99.12" in html
    assert 'data-tab="sp-vuln-reports"' in html


def test_vuln_seed_and_allowlist() -> None:
    specs = seed_catalog_specs()
    vuln = [s for s in specs if s["domain"] == "vulnerability"]
    keys = {s["action_key"] for s in vuln}
    assert "vuln.scan.one" in keys
    assert "vuln.scan.bulk" in keys
    assert keys <= ACTION_KEY_ALLOWLIST
    js = Path("frontend/static/js/portal/vuln.js").read_text(encoding="utf-8")
    assert "SVRMON24PortalVuln" in js
    assert "/api/portal/vuln/reports" in js


@pytest.mark.usefixtures("clean_db")
def test_meta_includes_vulnerability_domain(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    meta = client.get("/api/portal/meta", headers=auth_headers)
    assert meta.status_code == 200
    assert "vulnerability" in meta.json()["domains"]
    assert "sp_vuln_reports" in meta.json()["collections"]


@pytest.mark.usefixtures("clean_db")
def test_scan_one_produces_report_and_suggestions(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Ensure a server CI exists for the scan target.
    created_ci = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Server",
            "name": "vuln-scan-host-1",
            "environment": "lab",
            "hostname": "vuln-scan-host-1",
        },
    )
    assert created_ci.status_code in (200, 201), created_ci.text
    component_id = created_ci.json()["component_id"]

    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200
    item = next(
        i
        for i in client.get("/api/portal/catalog", headers=auth_headers).json()["items"]
        if i["key"] == "vuln.scan.one"
    )
    created = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": item["item_id"],
            "collect_mode": "agentless",
            "form_values": {"target_ci": component_id, "notes": "sp11"},
            "submit": True,
        },
    )
    assert created.status_code == 200, created.text
    req = created.json()
    assert (
        client.post(
            f"/api/itsm/changes/{req['change_id']}/transition",
            headers=auth_headers,
            json={"status": "approved"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/portal/changes/{req['request_id']}/sync",
            headers=auth_headers,
        ).status_code
        == 200
    )
    client.post(
        "/api/portal/admin/simulate-tick", headers=auth_headers, json={"limit": 20}
    )
    client.post(
        "/api/portal/admin/simulate-tick", headers=auth_headers, json={"limit": 20}
    )

    runs = client.get(
        "/api/portal/executions",
        headers=auth_headers,
        params={"request_id": req["request_id"]},
    )
    assert runs.status_code == 200
    done = runs.json()["items"][0]
    assert done["status"] == "succeeded"
    report_id = done["provisioned_facts"]["report_id"]
    assert report_id

    listed = client.get("/api/portal/vuln/reports", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] >= 1
    assert any(r["report_id"] == report_id for r in listed.json()["items"])

    detail = client.get(
        f"/api/portal/vuln/reports/{report_id}", headers=auth_headers
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["scope"] == "one"
    assert component_id in body["component_ids"]
    assert body["finding_count"] >= 1
    assert len(body["findings"]) == body["finding_count"]
    assert len(body["suggestions"]) == body["finding_count"]
    assert all(s.get("suggestion") for s in body["suggestions"])


@pytest.mark.usefixtures("clean_db")
def test_scan_bulk_multiple_servers(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    ids: list[str] = []
    for name in ("bulk-a", "bulk-b"):
        resp = client.post(
            "/api/components",
            headers=auth_headers,
            json={
                "component_type": "Server",
                "name": name,
                "environment": "lab",
                "hostname": name,
            },
        )
        assert resp.status_code in (200, 201), resp.text
        ids.append(resp.json()["component_id"])

    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200
    item = next(
        i
        for i in client.get("/api/portal/catalog", headers=auth_headers).json()["items"]
        if i["key"] == "vuln.scan.bulk"
    )
    created = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": item["item_id"],
            "form_values": {"component_ids": ", ".join(ids)},
            "submit": True,
        },
    )
    assert created.status_code == 200, created.text
    req = created.json()
    client.post(
        f"/api/itsm/changes/{req['change_id']}/transition",
        headers=auth_headers,
        json={"status": "approved"},
    )
    client.post(f"/api/portal/changes/{req['request_id']}/sync", headers=auth_headers)
    client.post(
        "/api/portal/admin/simulate-tick", headers=auth_headers, json={"limit": 20}
    )
    client.post(
        "/api/portal/admin/simulate-tick", headers=auth_headers, json={"limit": 20}
    )
    runs = client.get(
        "/api/portal/executions",
        headers=auth_headers,
        params={"request_id": req["request_id"]},
    )
    done = runs.json()["items"][0]
    assert done["status"] == "succeeded"
    report = client.get(
        f"/api/portal/vuln/reports/{done['provisioned_facts']['report_id']}",
        headers=auth_headers,
    ).json()
    assert report["scope"] == "bulk"
    assert set(report["component_ids"]) == set(ids)
    assert report["finding_count"] >= 2
