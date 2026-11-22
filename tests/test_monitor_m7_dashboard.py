"""Monitoring M7 — Dashboard aggregates + ITSM suggest-incident (0.78.0)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from tests.frontend_paths import FRONTEND_INDEX

MONITOR_DASH_JS = Path("frontend/static/js/monitor/dashboard.js")
MONITOR_ALERTS_JS = Path("frontend/static/js/monitor/alerts.js")
MONITOR_INDEX_JS = Path("frontend/static/js/monitor/index.js")


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


def test_version_bump_for_monitor_m7() -> None:
    assert __version__ == "0.78.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.78.0"' in html
    assert "monitor/dashboard.js?v=0.78.0" in html
    assert "monitor/alerts.js?v=0.78.0" in html
    assert "monitor/index.js?v=0.78.0" in html


def test_dashboard_and_suggest_ui_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'id="tab-monitor-dashboard"' in html
    assert 'id="monitorDashTargetsTotal"' in html
    assert 'id="monitorDashOpenAlerts"' in html
    assert 'id="monitorDashLogVolume"' in html
    assert 'id="monitorDashFileEvents"' in html
    assert 'id="monitorDashAlertsBody"' in html
    assert "placeholder-panel" not in html.split('id="tab-monitor-dashboard"')[1].split(
        'id="tab-monitor-servers"'
    )[0]
    assert "Create incident" in html.split('id="tab-monitor-alerts"')[1].split(
        'id="tab-itsm-dashboard"'
    )[0] or "draft→Apply" in html.split('id="tab-monitor-alerts"')[1].split(
        'id="tab-itsm-dashboard"'
    )[0]

    dash_js = MONITOR_DASH_JS.read_text(encoding="utf-8")
    assert "/api/monitor/dashboard" in dash_js
    assert "targets_total" in dash_js or "monitorDashTargetsTotal" in dash_js

    alerts_js = MONITOR_ALERTS_JS.read_text(encoding="utf-8")
    assert "suggest-incident" in alerts_js
    assert "createIncidentFromAlert" in alerts_js
    assert "itsm:incident:write" in alerts_js
    assert "SVRMON24ItsmApi.createIncident" in alerts_js
    assert "link-incident" in alerts_js
    assert "window.confirm" in alerts_js

    idx = MONITOR_INDEX_JS.read_text(encoding="utf-8")
    assert "SVRMON24MonitorDashboard" in idx


def test_dashboard_aggregates_match_collections(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.db import get_monitor_database
    from app.services import tenants as tenants_service
    from app.tenancy import MIGRATION_TENANT_ID, tenant_filter

    tenants_service.ensure_migration_tenant()
    cid = _create_ci(
        client,
        auth_headers,
        component_type="Server",
        name="M7 Dash Host",
        hostname="m7-dash.example",
        os_family="linux",
    )
    sync = client.post(
        "/api/monitor/targets/sync-from-cmdb", headers=auth_headers
    )
    assert sync.status_code == 200, sync.text

    tick = client.post(
        "/api/monitor/logs/simulate-tick", headers=auth_headers
    )
    assert tick.status_code == 200, tick.text

    # Ensure file events exist (seed via file monitoring list).
    files = client.get("/api/file-monitoring/targets", headers=auth_headers)
    assert files.status_code == 200, files.text

    # Fire at least one alert.
    created = client.post(
        "/api/monitor/alerts/rules",
        headers=auth_headers,
        json={
            "name": "M7 always-fire CPU",
            "severity": "error",
            "enabled": True,
            "condition": {
                "type": "threshold",
                "metric_name": "cpu_pct",
                "operator": "gte",
                "value": 0,
            },
            "scope": {"component_id": cid},
        },
    )
    assert created.status_code == 201, created.text
    evaluated = client.post(
        "/api/monitor/alerts/evaluate", headers=auth_headers
    )
    assert evaluated.status_code == 200, evaluated.text

    dash = client.get("/api/monitor/dashboard", headers=auth_headers)
    assert dash.status_code == 200, dash.text
    payload = dash.json()
    assert payload["execution_mode"] == "SIMULATED"
    assert payload["live_probes"] is False
    assert payload["targets_total"] >= 1
    assert payload["open_alerts"] >= 1
    assert payload["log_events_total"] >= 1
    assert isinstance(payload["targets_by_status"], dict)
    assert isinstance(payload["targets_by_domain"], dict)
    assert "server" in payload["targets_by_domain"]
    assert isinstance(payload["recent_open_alerts"], list)
    assert isinstance(payload["recent_log_events"], list)
    assert isinstance(payload["recent_file_events"], list)

    monitor = get_monitor_database()
    assert monitor is not None
    filt = tenant_filter(MIGRATION_TENANT_ID)
    assert payload["targets_total"] == monitor["monitor_targets"].count_documents(
        filt
    )
    open_q = {**filt, "status": {"$in": ["firing", "acked"]}}
    assert payload["open_alerts"] == monitor["alert_instances"].count_documents(
        open_q
    )
    assert payload["log_events_total"] == monitor["log_events"].count_documents(
        filt
    )
    assert payload["file_events_total"] == monitor[
        "file_version_events"
    ].count_documents(filt)


def test_suggest_incident_draft_only_then_human_apply(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.db import get_itsm_database, get_monitor_database
    from app.services import tenants as tenants_service
    from app.tenancy import MIGRATION_TENANT_ID, tenant_filter

    tenants_service.ensure_migration_tenant()
    cid = _create_ci(
        client,
        auth_headers,
        component_type="Server",
        name="M7 Suggest Host",
        hostname="m7-suggest.example",
        os_family="linux",
    )
    sync = client.post(
        "/api/monitor/targets/sync-from-cmdb", headers=auth_headers
    )
    assert sync.status_code == 200, sync.text
    created = client.post(
        "/api/monitor/alerts/rules",
        headers=auth_headers,
        json={
            "name": "M7 suggest rule",
            "severity": "critical",
            "enabled": True,
            "condition": {
                "type": "threshold",
                "metric_name": "cpu_pct",
                "operator": "gte",
                "value": 0,
            },
            "scope": {"component_id": cid},
        },
    )
    assert created.status_code == 201, created.text
    evaluated = client.post(
        "/api/monitor/alerts/evaluate", headers=auth_headers
    )
    assert evaluated.status_code == 200, evaluated.text
    instances = client.get(
        "/api/monitor/alerts/instances?status=firing,acked",
        headers=auth_headers,
    )
    assert instances.status_code == 200, instances.text
    items = instances.json()["items"]
    assert items, "expected at least one open alert"
    alert_id = items[0]["alert_id"]

    itsm_before = get_itsm_database()["itsm_incidents"].count_documents(
        tenant_filter(MIGRATION_TENANT_ID)
    )

    suggest = client.post(
        f"/api/monitor/alerts/instances/{alert_id}/suggest-incident",
        headers=auth_headers,
    )
    assert suggest.status_code == 200, suggest.text
    body = suggest.json()
    assert body["auto_create"] is False
    assert body["source"] == "rule_based_fallback"
    draft = body["draft"]
    assert draft["title"]
    assert draft["description"]
    assert draft["severity"] == "critical"
    assert draft["priority"] == "p1"
    assert draft["auto_create"] is False
    assert draft["ci_links"]
    assert draft["ci_links"][0]["component_id"] == cid
    assert "POST /api/itsm/incidents" in draft["apply_via"]

    # Suggest must not write ITSM.
    itsm_after_suggest = get_itsm_database()["itsm_incidents"].count_documents(
        tenant_filter(MIGRATION_TENANT_ID)
    )
    assert itsm_after_suggest == itsm_before

    # Human Apply via ITSM API.
    create = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": draft["title"],
            "description": draft["description"],
            "priority": draft["priority"],
            "category": draft.get("category") or "monitoring",
            "ci_links": draft["ci_links"],
        },
    )
    assert create.status_code == 201, create.text
    incident = create.json()
    iid = incident["incident_id"]

    linked = client.post(
        f"/api/monitor/alerts/instances/{alert_id}/link-incident",
        headers=auth_headers,
        json={"incident_id": iid},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["suggested_incident_id"] == iid

    monitor = get_monitor_database()
    alert_doc = monitor["alert_instances"].find_one(
        {**tenant_filter(MIGRATION_TENANT_ID), "alert_id": alert_id}
    )
    assert alert_doc is not None
    assert alert_doc["suggested_incident_id"] == iid


def test_suggest_incident_requires_write_permission(
    client: TestClient, auth_headers: dict[str, str], clean_db, monkeypatch
) -> None:
    from fastapi import HTTPException

    from app.permissions import PERM_MONITOR_ALERTS_WRITE
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()

    def deny_write(tenant, permission: str, *args, **kwargs):
        if permission == PERM_MONITOR_ALERTS_WRITE:
            raise HTTPException(
                status_code=403,
                detail=f"Missing permission: {PERM_MONITOR_ALERTS_WRITE}",
            )
        return None

    monkeypatch.setattr("app.permissions.assert_permission", deny_write)

    denied = client.post(
        "/api/monitor/alerts/instances/al-missing/suggest-incident",
        headers=auth_headers,
    )
    assert denied.status_code == 403, denied.text


def test_dashboard_requires_read_permission(
    client: TestClient, auth_headers: dict[str, str], clean_db, monkeypatch
) -> None:
    from fastapi import HTTPException

    from app.permissions import PERM_MONITOR_DASHBOARD_READ
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()

    def deny_read(tenant, permission: str, *args, **kwargs):
        if permission == PERM_MONITOR_DASHBOARD_READ:
            raise HTTPException(
                status_code=403,
                detail=f"Missing permission: {PERM_MONITOR_DASHBOARD_READ}",
            )
        return None

    monkeypatch.setattr("app.permissions.assert_permission", deny_read)
    denied = client.get("/api/monitor/dashboard", headers=auth_headers)
    assert denied.status_code == 403, denied.text
