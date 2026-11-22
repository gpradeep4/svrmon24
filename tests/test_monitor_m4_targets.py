"""Monitoring M4 — targets sync + domain health views (0.82.0)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from tests.frontend_paths import FRONTEND_INDEX

MONITOR_TARGETS_JS = Path("frontend/static/js/monitor/targets.js")
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


def test_version_bump_for_monitor_m4() -> None:
    assert __version__ == "0.82.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.82.0"' in html
    assert "monitor/targets.js?v=0.82.0" in html
    assert "monitor/index.js?v=0.82.0" in html


def test_domain_health_ui_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    for prefix in ("mtSrv", "mtNet", "mtApp", "mtMw", "mtDb"):
        assert f'id="{prefix}Body"' in html
        assert f'id="{prefix}Sync"' in html
        assert f'id="{prefix}CollectMode"' in html
    assert 'id="mtSrvOsFamily"' in html
    assert 'id="mtNetTargetKind"' in html
    assert "load_balancer" in html
    assert "access_point" in html
    js = MONITOR_TARGETS_JS.read_text(encoding="utf-8")
    assert "sync-from-cmdb" in js
    assert "Open CI" in js or "openCmdbCi" in js
    idx = MONITOR_INDEX_JS.read_text(encoding="utf-8")
    assert "SVRMON24MonitorTargets" in idx


def test_sync_from_cmdb_creates_targets_and_samples(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.db import get_monitor_database
    from app.services import tenants as tenants_service
    from app.tenancy import MIGRATION_TENANT_ID, tenant_filter

    tenants_service.ensure_migration_tenant()
    srv = _create_ci(
        client,
        auth_headers,
        component_type="Server",
        name="M4 Web",
        hostname="m4-web.example",
        os_family="RHEL",
        os_version="9.4",
    )
    net = _create_ci(
        client,
        auth_headers,
        component_type="Network",
        name="M4 Firewall",
        device_name="fw-m4",
        device_type="firewall",
        management_ip="10.1.1.1",
    )
    app = _create_ci(
        client,
        auth_headers,
        component_type="Application",
        name="M4 Billing",
        application_name="Billing",
        application_type="backend",
    )
    db = _create_ci(
        client,
        auth_headers,
        component_type="Database",
        name="M4 Orders DB",
        product_type="Oracle",
        product_version="19c",
    )
    # L7: Middleware CIs sync into monitor targets.
    mw = _create_ci(
        client,
        auth_headers,
        component_type="Middleware",
        name="M4 WebLogic",
        product_type="WebLogic",
        product_version="14.1",
        listen_address="mw.example.local",
        listen_port=7001,
    )

    sync = client.post(
        "/api/monitor/targets/sync-from-cmdb", headers=auth_headers
    )
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["created"] == 5
    assert body["execution_mode"] == "SIMULATED"
    assert body["live_probes"] is False
    assert body["domains"]["server"] == 1
    assert body["domains"]["network"] == 1
    assert body["domains"]["application"] == 1
    assert body["domains"]["database"] == 1
    assert body["domains"]["middleware"] == 1
    assert body["samples_seeded"] > 0
    assert set(body["collect_modes"].keys()) <= {"AGENTLESS", "AGENT"}
    assert sum(body["collect_modes"].values()) == 5

    listed = client.get("/api/monitor/targets", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert listed.json()["total"] == 5
    by_ci = {i["component_id"]: i for i in items}
    assert by_ci[srv]["domain"] == "server"
    assert by_ci[srv]["os_family"] == "linux"
    assert by_ci[srv]["collect_mode"] in {"AGENTLESS", "AGENT"}
    assert by_ci[net]["domain"] == "network"
    assert by_ci[net]["target_kind"] == "firewall"
    assert by_ci[app]["domain"] == "application"
    assert by_ci[db]["domain"] == "database"
    assert by_ci[db]["target_kind"] == "Oracle"
    assert by_ci[mw]["domain"] == "middleware"
    assert by_ci[mw]["target_kind"] == "WebLogic"
    assert all(i["execution_mode"] == "SIMULATED" for i in items)
    assert any(i.get("latest_metrics") for i in items)

    # Domain + kind + OS + collect_mode filters.
    servers = client.get(
        "/api/monitor/targets?domain=server&os_family=linux",
        headers=auth_headers,
    )
    assert servers.status_code == 200
    assert servers.json()["total"] == 1

    firewalls = client.get(
        "/api/monitor/targets?domain=network&target_kind=firewall",
        headers=auth_headers,
    )
    assert firewalls.status_code == 200
    assert firewalls.json()["total"] == 1

    mode = by_ci[srv]["collect_mode"]
    filtered = client.get(
        f"/api/monitor/targets?collect_mode={mode}",
        headers=auth_headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] >= 1
    assert all(i["collect_mode"] == mode for i in filtered.json()["items"])

    detail = client.get(
        f"/api/monitor/targets/{by_ci[srv]['target_id']}",
        headers=auth_headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["component_id"] == srv
    assert detail.json()["latest_metrics"]

    metrics = client.get(
        f"/api/monitor/targets/{by_ci[srv]['target_id']}/metrics?latest_only=true",
        headers=auth_headers,
    )
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["total"] >= 1
    assert metrics.json()["live_probes"] is False

    monitor = get_monitor_database()
    filt = tenant_filter(MIGRATION_TENANT_ID)
    assert monitor["monitor_targets"].count_documents(filt) == 5
    assert monitor["metric_samples"].count_documents(filt) >= 5

    # Idempotent re-sync updates, does not duplicate.
    again = client.post(
        "/api/monitor/targets/sync-from-cmdb", headers=auth_headers
    )
    assert again.status_code == 200, again.text
    assert again.json()["created"] == 0
    assert again.json()["updated"] == 5
    assert monitor["monitor_targets"].count_documents(filt) == 5


def test_sync_requires_write_permission(
    client: TestClient, auth_headers: dict[str, str], clean_db, monkeypatch
) -> None:
    """Viewer can list targets but cannot sync (monitor:targets:write)."""
    from fastapi import HTTPException

    from app.permissions import PERM_MONITOR_TARGETS_WRITE
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()

    def deny_write(tenant, permission: str, *args, **kwargs):
        if permission == PERM_MONITOR_TARGETS_WRITE:
            raise HTTPException(
                status_code=403,
                detail=f"Missing permission: {PERM_MONITOR_TARGETS_WRITE}",
            )
        return None

    monkeypatch.setattr("app.permissions.assert_permission", deny_write)

    listed = client.get("/api/monitor/targets", headers=auth_headers)
    assert listed.status_code == 200, listed.text

    denied = client.post(
        "/api/monitor/targets/sync-from-cmdb", headers=auth_headers
    )
    assert denied.status_code == 403, denied.text
    body = denied.json()
    detail = str(
        body.get("detail")
        or (body.get("error") or {}).get("message")
        or (body.get("error") or {}).get("details")
        or body
    )
    assert PERM_MONITOR_TARGETS_WRITE in detail


def test_monitor_targets_entitlement_enforced(
    client: TestClient, auth_headers: dict[str, str], clean_db, monkeypatch
) -> None:
    from app.services import entitlements as entitlements_service
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    _create_ci(
        client,
        auth_headers,
        component_type="Server",
        name="Entitled Host A",
        hostname="ent-a.example",
        os_family="linux",
    )
    _create_ci(
        client,
        auth_headers,
        component_type="Server",
        name="Entitled Host B",
        hostname="ent-b.example",
        os_family="linux",
    )

    monkeypatch.setattr(
        entitlements_service, "monitor_target_limit", lambda _tid: 1
    )

    sync = client.post(
        "/api/monitor/targets/sync-from-cmdb", headers=auth_headers
    )
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["created"] == 1
    assert body["entitlement_truncated"] is True
    assert body["skipped"] >= 1
    assert body["total"] == 1

    listed = client.get("/api/monitor/targets", headers=auth_headers)
    assert listed.json()["total"] == 1


def test_os_and_network_kind_normalization() -> None:
    from app.monitor.services.targets import (
        normalize_network_kind,
        normalize_os_family,
    )

    assert normalize_os_family("RHEL") == "linux"
    assert normalize_os_family("Windows Server") == "windows"
    assert normalize_os_family("macOS") == "macos"
    assert normalize_os_family("AIX") == "unix"
    assert normalize_network_kind("load_balancer") == "load_balancer"
    assert normalize_network_kind("NGFW") == "firewall"
    assert normalize_network_kind("wifi AP") == "access_point"
    assert normalize_network_kind("mystery-box") == "other_network"
