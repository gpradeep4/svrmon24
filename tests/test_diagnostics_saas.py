"""Master Phase 11 — Diagnostics (SIMULATED) SaaS tenancy regressions.

Covers tenant denial on run/list/get, SIMULATED-only banners, no remote probe
payloads, and max_diagnostic_runs entitlements stub.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.tenancy import MIGRATION_TENANT_ID

OTHER_TENANT_ID = "tenant-diag-saas-other"
OTHER_COMPONENT_ID = "diag-saas-other-srv"
OTHER_DIAG_ID = "diag-saas-other-001"


def _now():
    return datetime.now(timezone.utc)


def _seed_server(
    client: TestClient, headers: dict[str, str], component_id: str = "diag11-srv"
) -> str:
    response = client.post(
        "/api/components",
        headers=headers,
        json={
            "component_id": component_id,
            "component_type": "Server",
            "name": f"{component_id}-host",
            "environment": "prod",
            "status": "active",
            "hostname": f"{component_id}-host",
            "os_family": "RHEL",
            "os_version": "9.4",
        },
    )
    assert response.status_code == 201, response.text
    return component_id


@pytest.fixture()
def other_tenant_diag(clean_db):
    from app.db import get_database
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    db = get_database()
    now = _now()
    db["tenants"].update_one(
        {"tenant_id": OTHER_TENANT_ID},
        {
            "$setOnInsert": {
                "tenant_id": OTHER_TENANT_ID,
                "display_name": "Diag SaaS Other",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    db["cmdb_servers"].insert_one(
        {
            "component_id": OTHER_COMPONENT_ID,
            "component_type": "Server",
            "name": "other-diag-host",
            "environment": "lab",
            "status": "active",
            "hostname": "other-diag-host",
            "os_family": "RHEL",
            "os_version": "9",
            "tenant_id": OTHER_TENANT_ID,
            "created_at": now,
            "updated_at": now,
        }
    )
    db["diagnostic_history"].insert_one(
        {
            "diagnostic_id": OTHER_DIAG_ID,
            "timestamp": now,
            "created_at": now,
            "execution_mode": "SIMULATED",
            "profile_name": "basic-health",
            "component_id": OTHER_COMPONENT_ID,
            "component": {"component_id": OTHER_COMPONENT_ID},
            "checks": [],
            "summary": {"overall_status": "ok", "check_count": 0, "ok_count": 0},
            "labels": {
                "demo": True,
                "simulated": True,
                "real_telemetry": False,
                "banner": "SIMULATED / SYNTHETIC DEMO OUTPUT — NOT REAL TELEMETRY",
            },
            "tenant_id": OTHER_TENANT_ID,
        }
    )
    yield {
        "tenant_id": OTHER_TENANT_ID,
        "component_id": OTHER_COMPONENT_ID,
        "diagnostic_id": OTHER_DIAG_ID,
    }


def test_cross_tenant_diagnostic_get_list_denied(
    client: TestClient, auth_headers: dict[str, str], other_tenant_diag
) -> None:
    did = other_tenant_diag["diagnostic_id"]
    assert (
        client.get(f"/api/diagnostics/{did}", headers=auth_headers).status_code == 404
    )

    history = client.get("/api/diagnostics", headers=auth_headers)
    assert history.status_code == 200
    body = history.json()
    assert body.get("tenant_id") == MIGRATION_TENANT_ID
    assert body.get("execution_mode") == "SIMULATED"
    ids = [i["diagnostic_id"] for i in body.get("items") or []]
    assert did not in ids


def test_cross_tenant_component_run_denied(
    client: TestClient, auth_headers: dict[str, str], other_tenant_diag
) -> None:
    response = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={
            "component_id": other_tenant_diag["component_id"],
            "profile_name": "basic-health",
        },
    )
    assert response.status_code == 404


def test_run_stamps_tenant_and_simulated_labels(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    cid = _seed_server(client, auth_headers)
    created = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={"component_id": cid, "profile_name": "basic-health", "notes": "phase11"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["tenant_id"] == MIGRATION_TENANT_ID
    assert body["execution_mode"] == "SIMULATED"
    assert body["labels"]["real_telemetry"] is False
    assert body["labels"]["simulated"] is True
    assert "SIMULATED" in body["labels"]["banner"]
    assert body["safety"]["remote_execution"] is False
    assert body["safety"]["shell"] is False
    assert body["safety"]["sql"] is False
    assert body["safety"]["network_scan"] is False
    for check in body["checks"]:
        assert check["synthetic"] is True
        assert check["data_source"] == "SYNTHETIC_DEMO"

    fetched = client.get(
        f"/api/diagnostics/{body['diagnostic_id']}", headers=auth_headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == MIGRATION_TENANT_ID

    history = client.get(
        f"/api/diagnostics?component_id={cid}", headers=auth_headers
    )
    assert history.status_code == 200
    assert history.json()["tenant_id"] == MIGRATION_TENANT_ID
    assert any(
        i["diagnostic_id"] == body["diagnostic_id"]
        for i in history.json()["items"]
    )


def test_rejects_remote_probe_payload_keys(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    cid = _seed_server(client, auth_headers, "diag11-probe")
    for banned in ("probe", "live", "ssh", "sql", "shell", "command"):
        response = client.post(
            "/api/diagnostics",
            headers=auth_headers,
            json={
                "component_id": cid,
                "profile_name": "basic-health",
                banned: "should-fail",
            },
        )
        assert response.status_code == 422, banned


def test_max_diagnostic_runs_entitlement(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    ents = client.get("/api/entitlements", headers=auth_headers)
    assert ents.status_code == 200
    body = ents.json()
    assert body["billing_enabled"] is False
    assert body["limits"]["max_diagnostic_runs"] is None

    cid = _seed_server(client, auth_headers, "diag11-ent")
    first = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={"component_id": cid, "profile_name": "basic-health"},
    )
    assert first.status_code == 201, first.text

    with patch(
        "app.services.entitlements.diagnostic_run_limit", return_value=1
    ):
        blocked = client.post(
            "/api/diagnostics",
            headers=auth_headers,
            json={"component_id": cid, "profile_name": "basic-health"},
        )
        assert blocked.status_code == 403
        assert "diagnostic" in blocked.text.lower()

    # Unlimited path still works when stub returns None (default plan).
    second = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={"component_id": cid, "profile_name": "basic-health"},
    )
    assert second.status_code == 201, second.text


def test_profiles_remain_simulated_only(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/diagnostics/profiles", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["execution_mode"] == "SIMULATED"
    assert body["demo_only"] is True
    assert "SIMULATED" in (body.get("notice") or "")
    for profile in body["profiles"]:
        assert profile["execution_mode"] == "SIMULATED"
        assert profile.get("safety", {}).get("allows_remote_execution") is False


def test_diagnostics_ui_markers_and_version(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    html = client.get("/", headers=auth_headers).text
    assert 'id="diagComponentId"' in html
    assert 'id="diagProfile"' in html
    assert 'id="diagBanner"' in html
    assert 'id="diagSaasIntro"' in html
    assert 'id="diagEntitlementHint"' in html
    assert 'id="diagHistoryMeta"' in html
    assert "max_diagnostic_runs" in html
    assert "SIMULATED" in html
    from app import __version__

    assert __version__ in html
    js = client.get("/static/js/cmdb.js", headers=auth_headers).text
    assert "refreshDiagEntitlementHint" in js
    assert "max_diagnostic_runs" in js
    assert "Tenant-scoped history" in js
