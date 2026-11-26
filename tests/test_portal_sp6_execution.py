"""Service Portal SP6 — SIMULATED execution + CMDB sync (0.99.6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_portal_sp6() -> None:
    assert __version__ == "0.99.6"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.6"' in html
    assert "portal/executions.js?v=0.99.6" in html


def test_portal_executions_fe_markers() -> None:
    js = Path("frontend/static/js/portal/executions.js").read_text(encoding="utf-8")
    assert "SVRMON24PortalExecutions" in js
    assert "/api/portal/admin/simulate-tick" in js


def _form_values_for(item: dict) -> dict:
    values: dict = {}
    for field in (item.get("form_schema") or {}).get("fields") or []:
        name = field["name"]
        ftype = field.get("type")
        if ftype == "enum" and field.get("options"):
            values[name] = field["options"][0]
        elif ftype == "boolean":
            values[name] = True
        elif ftype == "integer" or ftype == "number":
            values[name] = int(field.get("default") or 1)
        elif name == "hostname":
            values[name] = "vm-demo-1"
        elif "region" in name:
            values[name] = "us-east-1"
        elif "sku" in name or "instance" in name:
            values[name] = "t3.small"
        else:
            values[name] = "demo"
    return values


@pytest.mark.usefixtures("clean_db")
def test_approve_enqueue_simulate_tick_and_cmdb_create(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200, seed.text
    item = next(
        i
        for i in client.get("/api/portal/catalog", headers=auth_headers).json()["items"]
        if i["key"] == "cloud.vm.provision"
    )
    assert item.get("cmdb_sync") == "create"

    created = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": item["item_id"],
            "collect_mode": "agentless",
            "form_values": _form_values_for(item),
            "submit": True,
        },
    )
    assert created.status_code == 200, created.text
    req = created.json()
    change_id = req["change_id"]
    request_id = req["request_id"]

    assert (
        client.post(
            f"/api/itsm/changes/{change_id}/transition",
            headers=auth_headers,
            json={"status": "approved", "comment": "go"},
        ).status_code
        == 200
    )

    synced = client.post(
        f"/api/portal/changes/{request_id}/sync",
        headers=auth_headers,
    )
    assert synced.status_code == 200, synced.text
    assert synced.json()["status"] in ("approved", "queued")

    tick1 = client.post(
        "/api/portal/admin/simulate-tick",
        headers=auth_headers,
        json={"limit": 20},
    )
    assert tick1.status_code == 200, tick1.text
    tick2 = client.post(
        "/api/portal/admin/simulate-tick",
        headers=auth_headers,
        json={"limit": 20},
    )
    assert tick2.status_code == 200, tick2.text
    assert tick1.json()["advanced"] + tick2.json()["advanced"] >= 1

    runs = client.get("/api/portal/executions", headers=auth_headers)
    assert runs.status_code == 200, runs.text
    items = runs.json()["items"]
    assert any(r["request_id"] == request_id for r in items)
    done = next(r for r in items if r["request_id"] == request_id)
    assert done["status"] == "succeeded"
    assert done["execution_mode"] == "SIMULATED"

    detail = client.get(
        f"/api/portal/requests/{request_id}", headers=auth_headers
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "succeeded"
    assert body.get("cmdb_sync_status") in ("succeeded", "failed", "pending", "none")
    if body.get("cmdb_sync_status") == "succeeded":
        assert body.get("component_id")


@pytest.mark.usefixtures("clean_db")
def test_live_execution_fail_closed(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200
    item = next(
        i
        for i in client.get("/api/portal/catalog", headers=auth_headers).json()["items"]
        if i["key"] == "generic.daily.access_request"
    )
    created = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": item["item_id"],
            "form_values": {
                "who": "eve",
                "what": "vpn",
                "why": "demo",
                "duration_days": 3,
            },
            "requested_execution_mode": "LIVE",
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
    synced = client.post(
        f"/api/portal/changes/{req['request_id']}/sync",
        headers=auth_headers,
    )
    assert synced.status_code == 200
    runs = client.get(
        "/api/portal/executions",
        headers=auth_headers,
        params={"request_id": req["request_id"]},
    )
    assert runs.status_code == 200
    assert runs.json()["total"] == 0
