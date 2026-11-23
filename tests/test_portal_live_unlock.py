"""Service Portal SP10 — LIVE execute unlock + Terraform cloud (0.94.0)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import get_settings
from app.portal.services.adapters import terraform_cloud as tf_cloud
from app.services import tenants as tenants_service

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_portal_live_unlock() -> None:
    assert __version__ == "0.94.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.94.0"' in html
    assert "portal/executions.js?v=0.94.0" in html


def test_terraform_lab_plan_and_apply_without_binary() -> None:
    values = {
        "provider": "aws",
        "cloud_account_ref": "acct-demo",
        "cloud_region": "us-east-1",
        "instance_type": "t3.small",
        "os_image": "linux-ubuntu-22.04",
        "hostname": "tf-lab-1",
    }
    with patch.object(tf_cloud.shutil, "which", return_value=None):
        plan = tf_cloud.provision_vm(values, dry_run=True)
        apply = tf_cloud.provision_vm(values, dry_run=False)
    assert plan["ok"] is True and plan["dry_run"] is True and plan["lab_mode"] is True
    assert apply["ok"] is True and apply["dry_run"] is False
    assert apply["provisioned_facts"]["hostname"] == "tf-lab-1"
    assert apply["provisioned_facts"]["path"] == "terraform"


def test_adapters_package_markers() -> None:
    root = Path("app/portal/services/adapters")
    assert (root / "terraform_cloud.py").is_file()
    assert (root / "agentless.py").is_file()
    assert (root / "agent.py").is_file()
    text = (root / "terraform_cloud.py").read_text(encoding="utf-8")
    assert "terraform" in text.lower()
    assert "null_resource" in text


def _opt_in_live(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERVICE_PORTAL_LIVE_EXEC_ENABLED", "true")
    monkeypatch.setenv("SERVICE_PORTAL_LIVE_AGENTLESS_ENABLED", "true")
    monkeypatch.setenv("SERVICE_PORTAL_LIVE_AGENT_ENABLED", "true")
    monkeypatch.setenv("SERVICE_PORTAL_EGRESS_ALLOWLIST", "127.0.0.1,localhost,example.com")
    get_settings.cache_clear()
    tenants_service.ensure_migration_tenant()
    patched = client.patch(
        "/api/portal/admin/live-settings",
        headers=auth_headers,
        json={
            "sp_live_opt_in": True,
            "sp_live_agentless_opt_in": True,
            "sp_live_agent_opt_in": True,
        },
    )
    assert patched.status_code == 200, patched.text


def _form_values_for(item: dict) -> dict:
    values: dict = {}
    for field in (item.get("form_schema") or {}).get("fields") or []:
        name = field["name"]
        ftype = field.get("type")
        if ftype == "enum" and field.get("options"):
            values[name] = field["options"][0]
        elif ftype == "boolean":
            values[name] = True
        elif ftype in ("integer", "number"):
            values[name] = int(field.get("default") or 1)
        elif name == "hostname":
            values[name] = "live-vm-1"
        elif "region" in name:
            values[name] = "us-east-1"
        elif "sku" in name or "instance" in name:
            values[name] = "t3.small"
        else:
            values[name] = "demo"
    return values


def _approve_and_sync(
    client: TestClient, auth_headers: dict[str, str], req: dict
) -> dict:
    assert (
        client.post(
            f"/api/itsm/changes/{req['change_id']}/transition",
            headers=auth_headers,
            json={"status": "approved", "comment": "go live"},
        ).status_code
        == 200
    )
    synced = client.post(
        f"/api/portal/changes/{req['request_id']}/sync",
        headers=auth_headers,
    )
    assert synced.status_code == 200, synced.text
    return synced.json()


@pytest.mark.usefixtures("clean_db")
def test_meta_live_adapters_true(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    meta = client.get("/api/portal/meta", headers=auth_headers)
    assert meta.status_code == 200
    body = meta.json()
    assert body["live_adapters"] is True
    assert body.get("cloud_provision") == "terraform"
    assert body["live_gates"]["live_adapters"] is True


@pytest.mark.usefixtures("clean_db")
def test_live_still_fail_closed_without_gates(
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
    _approve_and_sync(client, auth_headers, req)
    enq = client.post(
        f"/api/portal/executions/{req['request_id']}/requeue",
        headers=auth_headers,
    )
    assert enq.status_code == 403, enq.text


@pytest.mark.usefixtures("clean_db")
def test_live_generic_agentless_when_gates_open(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _opt_in_live(client, auth_headers, monkeypatch)
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
            "collect_mode": "agentless",
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
    _approve_and_sync(client, auth_headers, req)

    tick1 = client.post(
        "/api/portal/admin/simulate-tick",
        headers=auth_headers,
        json={"limit": 20},
    )
    tick2 = client.post(
        "/api/portal/admin/simulate-tick",
        headers=auth_headers,
        json={"limit": 20},
    )
    assert tick1.status_code == 200 and tick2.status_code == 200
    runs = client.get(
        "/api/portal/executions",
        headers=auth_headers,
        params={"request_id": req["request_id"]},
    )
    assert runs.status_code == 200
    items = runs.json()["items"]
    assert items, "expected LIVE run"
    done = items[0]
    assert done["execution_mode"] == "LIVE"
    assert done["status"] == "succeeded"
    assert done["provisioned_facts"]["live"] is True
    assert done["provisioned_facts"]["path"] == "agentless"
    get_settings.cache_clear()


@pytest.mark.usefixtures("clean_db")
def test_live_cloud_vm_terraform_lab(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _opt_in_live(client, auth_headers, monkeypatch)
    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200
    item = next(
        i
        for i in client.get("/api/portal/catalog", headers=auth_headers).json()["items"]
        if i["key"] == "cloud.vm.provision"
    )
    created = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": item["item_id"],
            "collect_mode": "agentless",
            "form_values": _form_values_for(item),
            "requested_execution_mode": "LIVE",
            "submit": True,
        },
    )
    assert created.status_code == 200, created.text
    req = created.json()
    _approve_and_sync(client, auth_headers, req)
    with patch.object(tf_cloud.shutil, "which", return_value=None):
        client.post(
            "/api/portal/admin/simulate-tick",
            headers=auth_headers,
            json={"limit": 20},
        )
        client.post(
            "/api/portal/admin/simulate-tick",
            headers=auth_headers,
            json={"limit": 20},
        )
    runs = client.get(
        "/api/portal/executions",
        headers=auth_headers,
        params={"request_id": req["request_id"]},
    )
    done = runs.json()["items"][0]
    assert done["status"] == "succeeded"
    assert done["execution_mode"] == "LIVE"
    assert done["provisioned_facts"]["path"] == "terraform"
    assert done["provisioned_facts"].get("lab_mode") is True
    detail = client.get(
        f"/api/portal/requests/{req['request_id']}", headers=auth_headers
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "succeeded"
    assert body.get("cmdb_sync_status") in ("succeeded", "failed", "none")
    get_settings.cache_clear()


@pytest.mark.usefixtures("clean_db")
def test_live_agent_dispatch_and_dry_run(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _opt_in_live(client, auth_headers, monkeypatch)
    seed = client.post("/api/portal/catalog/seed", headers=auth_headers)
    assert seed.status_code == 200
    item = next(
        i
        for i in client.get("/api/portal/catalog", headers=auth_headers).json()["items"]
        if i["key"] == "other.checklist.complete"
    )
    # LIVE agent path
    created = client.post(
        "/api/portal/requests",
        headers=auth_headers,
        json={
            "item_id": item["item_id"],
            "collect_mode": "agent",
            "form_values": {"summary": "live agent", "steps": "1. a"},
            "requested_execution_mode": "LIVE",
            "submit": True,
        },
    )
    assert created.status_code == 200, created.text
    req = created.json()
    _approve_and_sync(client, auth_headers, req)
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
    assert done["execution_mode"] == "LIVE"
    assert done["collect_mode"] == "agent"
    assert done["status"] == "succeeded"
    assert done["provisioned_facts"]["path"] == "agent"
    assert done["provisioned_facts"].get("agent_job_id")

    # DRY_RUN with gates on uses live dry-run adapter
    dry = client.post(
        f"/api/portal/executions/{req['request_id']}/requeue",
        headers=auth_headers,
        json={"dry_run": True, "collect_mode": "agentless"},
    )
    assert dry.status_code == 200, dry.text
    assert dry.json().get("dry_run") is True or dry.json().get("execution_mode") == "DRY_RUN"
    client.post(
        "/api/portal/admin/simulate-tick", headers=auth_headers, json={"limit": 20}
    )
    client.post(
        "/api/portal/admin/simulate-tick", headers=auth_headers, json={"limit": 20}
    )
    get_settings.cache_clear()
