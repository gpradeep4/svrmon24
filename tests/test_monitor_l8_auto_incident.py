"""Monitoring L8 — optional auto-create ITSM incidents from alerts (0.91.0)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import get_settings
from app.db import get_database, get_itsm_database, get_monitor_database
from app.services import tenants as tenants_service
from app.tenancy import MIGRATION_TENANT_ID, tenant_filter
from tests.frontend_paths import FRONTEND_INDEX

MONITOR_ALERTS_JS = Path("frontend/static/js/monitor/alerts.js")


@pytest.fixture()
def live_platform_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONITOR_LIVE_PROBES_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _create_ci(
    client: TestClient,
    headers: dict[str, str],
    *,
    component_type: str,
    name: str,
    **extra: object,
) -> str:
    payload = {
        "component_type": component_type,
        "name": name,
        "environment": "prod",
        "status": "active",
        **extra,
    }
    resp = client.post("/api/components", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["component_id"]


def _enable_auto_incident_gates(
    client: TestClient, headers: dict[str, str]
) -> None:
    patched = client.patch(
        "/api/monitor/admin/live-settings",
        headers=headers,
        json={
            "monitor_live_opt_in": True,
            "monitor_auto_incident_opt_in": True,
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["live_gates"]["auto_incident"] is True


def _fire_threshold_alert(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str,
    auto_incident: bool,
    component_id: str,
) -> str:
    sync = client.post("/api/monitor/targets/sync-from-cmdb", headers=headers)
    assert sync.status_code == 200, sync.text
    created = client.post(
        "/api/monitor/alerts/rules",
        headers=headers,
        json={
            "name": name,
            "severity": "critical",
            "enabled": True,
            "auto_incident": auto_incident,
            "condition": {
                "type": "threshold",
                "metric_name": "cpu_pct",
                "operator": "gte",
                "value": 0,
            },
            "scope": {"component_id": component_id},
        },
    )
    assert created.status_code == 201, created.text
    evaluated = client.post("/api/monitor/alerts/evaluate", headers=headers)
    assert evaluated.status_code == 200, evaluated.text
    instances = client.get(
        "/api/monitor/alerts/instances?status=firing,acked",
        headers=headers,
    )
    assert instances.status_code == 200, instances.text
    items = instances.json()["items"]
    assert items, "expected at least one open alert"
    # Prefer the alert for this rule name.
    for item in items:
        if item.get("rule_name") == name:
            return item["alert_id"]
    return items[0]["alert_id"]


def test_version_bump_for_monitor_l8() -> None:
    assert __version__ == "0.91.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.91.0"' in html
    assert "monitor/alerts.js?v=0.91.0" in html
    assert "maRuleAutoIncident" in html
    assert "Auto-create ITSM incident" in html

    alerts_js = MONITOR_ALERTS_JS.read_text(encoding="utf-8")
    assert "auto_incident" in alerts_js
    assert "live_gates" in alerts_js
    assert "refreshAutoIncidentGate" in alerts_js
    assert "toggleRuleAutoIncident" in alerts_js


def test_entitlement_catalog_includes_auto_incidents_per_day() -> None:
    from app.services import entitlements as entitlements_service

    plans = {p["plan_code"]: p for p in entitlements_service.list_plans()}
    starter = plans["starter"]["limits"]
    standard = plans["standard"]["limits"]
    unlimited = plans["legacy_unlimited"]["limits"]
    assert starter["monitor_auto_incidents_per_day"] == 10
    assert standard["monitor_auto_incidents_per_day"] == 100
    assert unlimited["monitor_auto_incidents_per_day"] is None


def test_flag_off_never_auto_creates(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    # Platform on but tenant auto-incident opt-in OFF (default).
    client.patch(
        "/api/monitor/admin/live-settings",
        headers=auth_headers,
        json={"monitor_live_opt_in": True},
    )
    meta = client.get("/api/monitor/meta", headers=auth_headers)
    assert meta.status_code == 200
    assert meta.json()["live_gates"]["auto_incident"] is False

    cid = _create_ci(
        client,
        auth_headers,
        component_type="Server",
        name="L8 Flag Off Host",
        hostname="l8-off.example",
        os_family="linux",
    )
    itsm_before = get_itsm_database()["itsm_incidents"].count_documents(
        tenant_filter(MIGRATION_TENANT_ID)
    )
    alert_id = _fire_threshold_alert(
        client,
        auth_headers,
        name="L8 flag-off rule",
        auto_incident=True,  # rule wants it, but gate off
        component_id=cid,
    )
    itsm_after = get_itsm_database()["itsm_incidents"].count_documents(
        tenant_filter(MIGRATION_TENANT_ID)
    )
    assert itsm_after == itsm_before

    alert = get_monitor_database()["alert_instances"].find_one(
        {**tenant_filter(MIGRATION_TENANT_ID), "alert_id": alert_id}
    )
    assert alert is not None
    assert alert.get("auto_created_incident_id") is None
    assert alert.get("auto_create_status") == "skipped"

    # Suggest-incident still works (draft only).
    suggest = client.post(
        f"/api/monitor/alerts/instances/{alert_id}/suggest-incident",
        headers=auth_headers,
    )
    assert suggest.status_code == 200, suggest.text
    assert suggest.json()["auto_create"] is False
    assert suggest.json()["draft"]["auto_create"] is False


def test_flag_on_rule_creates_via_itsm_client(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    _enable_auto_incident_gates(client, auth_headers)

    cid = _create_ci(
        client,
        auth_headers,
        component_type="Server",
        name="L8 Auto Host",
        hostname="l8-auto.example",
        os_family="linux",
    )
    itsm_before = get_itsm_database()["itsm_incidents"].count_documents(
        tenant_filter(MIGRATION_TENANT_ID)
    )
    alert_id = _fire_threshold_alert(
        client,
        auth_headers,
        name="L8 auto-create rule",
        auto_incident=True,
        component_id=cid,
    )
    itsm_after = get_itsm_database()["itsm_incidents"].count_documents(
        tenant_filter(MIGRATION_TENANT_ID)
    )
    assert itsm_after == itsm_before + 1

    alert = get_monitor_database()["alert_instances"].find_one(
        {**tenant_filter(MIGRATION_TENANT_ID), "alert_id": alert_id}
    )
    assert alert is not None
    assert alert.get("auto_create_status") == "created"
    iid = alert.get("auto_created_incident_id")
    assert iid
    assert alert.get("suggested_incident_id") == iid

    incident = get_itsm_database()["itsm_incidents"].find_one(
        {**tenant_filter(MIGRATION_TENANT_ID), "incident_id": iid}
    )
    assert incident is not None
    assert incident.get("created_by") == "monitor-auto-incident"
    assert incident.get("category") == "monitoring"
    assert incident.get("priority") == "p1"
    assert "auto-created" in (incident.get("description") or "").lower()

    # Audit row for auto-create.
    events = list(
        get_database()["audit_events"].find(
            {
                **tenant_filter(MIGRATION_TENANT_ID),
                "action": "monitor.alerts.auto_incident",
                "resource_id": alert_id,
            }
        )
    )
    assert events, "expected audit event for auto-incident create"
    assert events[-1]["details"].get("outcome") == "created"
    assert events[-1]["details"].get("incident_id") == iid
    assert events[-1]["actor"].get("username") == "monitor-auto-incident"


def test_no_duplicate_auto_incident_while_open(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    _enable_auto_incident_gates(client, auth_headers)

    cid = _create_ci(
        client,
        auth_headers,
        component_type="Server",
        name="L8 Dedup Host",
        hostname="l8-dedup.example",
        os_family="linux",
    )
    alert_id = _fire_threshold_alert(
        client,
        auth_headers,
        name="L8 dedup rule",
        auto_incident=True,
        component_id=cid,
    )
    alert = get_monitor_database()["alert_instances"].find_one(
        {**tenant_filter(MIGRATION_TENANT_ID), "alert_id": alert_id}
    )
    assert alert is not None
    first_iid = alert["auto_created_incident_id"]
    itsm_count = get_itsm_database()["itsm_incidents"].count_documents(
        tenant_filter(MIGRATION_TENANT_ID)
    )

    # Re-evaluate: open fingerprint skips new alert → no second incident.
    again = client.post("/api/monitor/alerts/evaluate", headers=auth_headers)
    assert again.status_code == 200, again.text
    assert again.json()["created"] == 0
    itsm_after = get_itsm_database()["itsm_incidents"].count_documents(
        tenant_filter(MIGRATION_TENANT_ID)
    )
    assert itsm_after == itsm_count

    alert2 = get_monitor_database()["alert_instances"].find_one(
        {**tenant_filter(MIGRATION_TENANT_ID), "alert_id": alert_id}
    )
    assert alert2["auto_created_incident_id"] == first_iid


def test_rule_auto_incident_off_does_not_create(
    live_platform_on,
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
) -> None:
    tenants_service.ensure_migration_tenant()
    _enable_auto_incident_gates(client, auth_headers)

    cid = _create_ci(
        client,
        auth_headers,
        component_type="Server",
        name="L8 Rule Off Host",
        hostname="l8-rule-off.example",
        os_family="linux",
    )
    itsm_before = get_itsm_database()["itsm_incidents"].count_documents(
        tenant_filter(MIGRATION_TENANT_ID)
    )
    alert_id = _fire_threshold_alert(
        client,
        auth_headers,
        name="L8 rule-off",
        auto_incident=False,
        component_id=cid,
    )
    itsm_after = get_itsm_database()["itsm_incidents"].count_documents(
        tenant_filter(MIGRATION_TENANT_ID)
    )
    assert itsm_after == itsm_before
    alert = get_monitor_database()["alert_instances"].find_one(
        {**tenant_filter(MIGRATION_TENANT_ID), "alert_id": alert_id}
    )
    assert alert.get("auto_created_incident_id") is None
    assert alert.get("auto_create_status") is None


def test_itsm_client_is_service_boundary_not_direct_mongo() -> None:
    src = Path("app/monitor/services/itsm_client.py").read_text(encoding="utf-8")
    assert "create_incident_from_alert" in src
    assert "incidents_service.create_incident" in src
    assert "AUTO_INCIDENT_ACTOR" in src
    # Must not insert into ITSM collections from the monitor client.
    assert 'insert_one' not in src
    assert "itsm_incidents" not in src
