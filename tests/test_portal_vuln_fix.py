"""Service Portal SP12 — Vulnerability fix + Change approval + rollback (0.99.4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.portal.services.seed import ACTION_KEY_ALLOWLIST, seed_catalog_specs
from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_portal_vuln_fix() -> None:
    assert __version__ == "0.99.4"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.4"' in html
    assert "portal/vuln.js?v=0.99.4" in html


def test_fix_and_rollback_in_seed() -> None:
    specs = {s["action_key"]: s for s in seed_catalog_specs()}
    assert "vuln.fix.apply" in specs
    assert "vuln.fix.rollback" in specs
    assert specs["vuln.fix.apply"]["change_type_key"].startswith("sp.vuln.fix")
    assert "vuln.fix.apply" in ACTION_KEY_ALLOWLIST
    assert "vuln.fix.rollback" in ACTION_KEY_ALLOWLIST
    js = Path("frontend/static/js/portal/vuln.js").read_text(encoding="utf-8")
    assert "vuln.fix.apply" in js
    assert "vuln.fix.rollback" in js
    assert "Request fix" in js


def _create_server(client: TestClient, headers: dict[str, str], name: str) -> str:
    resp = client.post(
        "/api/components",
        headers=headers,
        json={
            "component_type": "Server",
            "name": name,
            "environment": "lab",
            "hostname": name,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["component_id"]


def _approve_sync_tick(
    client: TestClient, headers: dict[str, str], req: dict
) -> dict:
    assert (
        client.post(
            f"/api/itsm/changes/{req['change_id']}/transition",
            headers=headers,
            json={"status": "approved", "comment": "sp12"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/portal/changes/{req['request_id']}/sync",
            headers=headers,
        ).status_code
        == 200
    )
    client.post(
        "/api/portal/admin/simulate-tick", headers=headers, json={"limit": 20}
    )
    client.post(
        "/api/portal/admin/simulate-tick", headers=headers, json={"limit": 20}
    )
    runs = client.get(
        "/api/portal/executions",
        headers=headers,
        params={"request_id": req["request_id"]},
    )
    assert runs.status_code == 200
    assert runs.json()["items"], "expected execution run"
    return runs.json()["items"][0]


def _item(client: TestClient, headers: dict[str, str], key: str) -> dict:
    items = client.get("/api/portal/catalog", headers=headers).json()["items"]
    return next(i for i in items if i["key"] == key)


@pytest.mark.usefixtures("clean_db")
def test_fix_requires_change_then_stores_rollback(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    component_id = _create_server(client, auth_headers, "fix-host-1")
    assert client.post("/api/portal/catalog/seed", headers=auth_headers).status_code == 200

    # Scan first
    scan_item = _item(client, auth_headers, "vuln.scan.one")
    scan_req = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": scan_item["item_id"],
            "form_values": {"target_ci": component_id},
            "submit": True,
        },
    )
    assert scan_req.status_code == 200, scan_req.text
    scan_run = _approve_sync_tick(client, auth_headers, scan_req.json())
    assert scan_run["status"] == "succeeded"
    report_id = scan_run["provisioned_facts"]["report_id"]
    report = client.get(
        f"/api/portal/vuln/reports/{report_id}", headers=auth_headers
    ).json()
    finding = report["findings"][0]
    vuln_id = finding["vuln_id"]

    # Fix via Change-gated catalog request
    fix_item = _item(client, auth_headers, "vuln.fix.apply")
    fix_req = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": fix_item["item_id"],
            "form_values": {
                "report_id": report_id,
                "vuln_id": vuln_id,
                "component_ids": component_id,
                "finding_ids": finding["finding_id"],
            },
            "submit": True,
        },
    )
    assert fix_req.status_code == 200, fix_req.text
    body = fix_req.json()
    assert body.get("change_id"), "fix must attach ITSM Change"
    assert body.get("change_type_key") == "sp.vuln.fix.apply"

    fix_run = _approve_sync_tick(client, auth_headers, body)
    assert fix_run["status"] == "succeeded"
    facts = fix_run["provisioned_facts"]
    assert facts.get("rollback_available") is True
    assert facts.get("rollback_token")
    assert facts.get("vuln_id") == vuln_id
    assert facts.get("previous_version")
    assert facts.get("applied_version")

    refreshed = client.get(
        f"/api/portal/vuln/reports/{report_id}", headers=auth_headers
    ).json()
    fixed = next(
        f for f in refreshed["findings"] if f["finding_id"] == finding["finding_id"]
    )
    assert fixed["status"] == "fixed"
    assert fixed.get("fix_run_id") == fix_run["run_id"]

    # Rollback via Change
    rb_item = _item(client, auth_headers, "vuln.fix.rollback")
    rb_req = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": rb_item["item_id"],
            "form_values": {"fix_run_id": fix_run["run_id"]},
            "submit": True,
        },
    )
    assert rb_req.status_code == 200, rb_req.text
    assert rb_req.json().get("change_id")
    rb_run = _approve_sync_tick(client, auth_headers, rb_req.json())
    assert rb_run["status"] == "succeeded"
    assert rb_run["provisioned_facts"].get("rollback_of_run_id") == fix_run["run_id"]
    assert rb_run["provisioned_facts"].get("restored_version") == facts["previous_version"]

    after = client.get(
        f"/api/portal/vuln/reports/{report_id}", headers=auth_headers
    ).json()
    rolled = next(
        f for f in after["findings"] if f["finding_id"] == finding["finding_id"]
    )
    assert rolled["status"] == "rolled_back"


@pytest.mark.usefixtures("clean_db")
def test_fix_dry_run_does_not_mutate_findings(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    component_id = _create_server(client, auth_headers, "fix-dry-1")
    assert client.post("/api/portal/catalog/seed", headers=auth_headers).status_code == 200
    scan_item = _item(client, auth_headers, "vuln.scan.one")
    scan_req = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": scan_item["item_id"],
            "form_values": {"target_ci": component_id},
            "submit": True,
        },
    ).json()
    scan_run = _approve_sync_tick(client, auth_headers, scan_req)
    report_id = scan_run["provisioned_facts"]["report_id"]
    finding = client.get(
        f"/api/portal/vuln/reports/{report_id}", headers=auth_headers
    ).json()["findings"][0]

    fix_item = _item(client, auth_headers, "vuln.fix.apply")
    fix_req = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": fix_item["item_id"],
            "form_values": {
                "report_id": report_id,
                "vuln_id": finding["vuln_id"],
                "component_ids": component_id,
            },
            "requested_execution_mode": "DRY_RUN",
            "submit": True,
        },
    )
    assert fix_req.status_code == 200, fix_req.text
    # Approve + tick dry-run
    req = fix_req.json()
    # Requeue path uses dry_run on request — sync enqueue may use SIMULATED
    # unless requested_execution_mode preserved. Force requeue dry_run.
    client.post(
        f"/api/itsm/changes/{req['change_id']}/transition",
        headers=auth_headers,
        json={"status": "approved"},
    )
    client.post(f"/api/portal/changes/{req['request_id']}/sync", headers=auth_headers)
    dry = client.post(
        f"/api/portal/executions/{req['request_id']}/requeue",
        headers=auth_headers,
        json={"dry_run": True},
    )
    assert dry.status_code == 200, dry.text
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
    ).json()["items"]
    dry_run = next(r for r in runs if r.get("dry_run"))
    assert dry_run["status"] == "succeeded"
    assert dry_run["provisioned_facts"].get("dry_run") is True

    refreshed = client.get(
        f"/api/portal/vuln/reports/{report_id}", headers=auth_headers
    ).json()
    still = next(
        f for f in refreshed["findings"] if f["finding_id"] == finding["finding_id"]
    )
    assert still["status"] == "open"
