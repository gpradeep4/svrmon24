"""Monitoring L7 — Middleware nav + CMDB sync + suggest-check (0.88.0)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from tests.frontend_paths import FRONTEND_INDEX

MONITOR_TARGETS_JS = Path("frontend/static/js/monitor/targets.js")
MONITOR_INDEX_JS = Path("frontend/static/js/monitor/index.js")
CMDB_JS = Path("frontend/static/js/cmdb.js")
ROUTING_JS = Path("frontend/static/js/itsm/routing.js")


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


def test_version_bump_for_monitor_l7() -> None:
    assert __version__ == "0.88.0"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.88.0"' in html
    assert "monitor/targets.js?v=0.88.0" in html
    assert "monitor/index.js?v=0.88.0" in html


def test_middleware_nav_and_tab_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'data-tab="monitor-middleware"' in html
    assert 'id="tab-monitor-middleware"' in html
    assert 'id="mtMwBody"' in html
    assert 'id="mtMwSync"' in html
    assert 'id="mtMwBanner"' in html
    assert "Middleware (Monitoring)" in html

    apps = html.index('data-tab="monitor-applications"')
    mw = html.index('data-tab="monitor-middleware"')
    dbs = html.index('data-tab="monitor-databases"')
    assert apps < mw < dbs

    js = MONITOR_TARGETS_JS.read_text(encoding="utf-8")
    assert '"monitor-middleware": "middleware"' in js
    assert "mtMw" in js
    assert "suggest-check" in js
    assert "Suggest check" in js
    assert "Open CI" in js or "openCmdbCi" in js

    idx = MONITOR_INDEX_JS.read_text(encoding="utf-8")
    assert "monitor-middleware" in idx
    assert "Middleware (Monitoring)" in idx

    cmdb = CMDB_JS.read_text(encoding="utf-8")
    assert '"monitor-middleware": "monitoring"' in cmdb

    routing = ROUTING_JS.read_text(encoding="utf-8")
    assert '"monitor-middleware"' in routing


def test_cmdb_client_maps_middleware_domain() -> None:
    from app.monitor.services import cmdb_client

    assert cmdb_client.DOMAIN_COMPONENT_TYPES["middleware"] == "Middleware"
    assert "Middleware" in cmdb_client.MONITORABLE_COMPONENT_TYPES
    assert cmdb_client.domain_for_component_type("Middleware") == "middleware"
    assert cmdb_client.domain_for_component_type("Server") == "server"


def test_sync_creates_middleware_targets(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    mw = _create_ci(
        client,
        auth_headers,
        component_type="Middleware",
        name="L7 Kafka",
        product_type="Kafka",
        product_version="3.6",
        instance_name="kafka-prod-1",
        listen_address="kafka.lab.example",
        listen_port=9092,
    )
    _create_ci(
        client,
        auth_headers,
        component_type="Server",
        name="L7 Host",
        hostname="l7-host.example",
        os_family="linux",
    )

    sync = client.post(
        "/api/monitor/targets/sync-from-cmdb", headers=auth_headers
    )
    assert sync.status_code == 200, sync.text
    body = sync.json()
    assert body["domains"]["middleware"] == 1
    assert body["domains"]["server"] == 1
    assert body["created"] == 2

    listed = client.get(
        "/api/monitor/targets?domain=middleware", headers=auth_headers
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert listed.json()["total"] == 1
    row = items[0]
    assert row["component_id"] == mw
    assert row["domain"] == "middleware"
    assert row["target_kind"] == "Kafka"
    assert row["component_type"] == "Middleware"
    assert row["execution_mode"] == "SIMULATED"
    assert row["collect_mode"] in {"AGENTLESS", "AGENT"}
    assert row.get("latest_metrics")


def test_suggest_check_from_listen_fields(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    mw = _create_ci(
        client,
        auth_headers,
        component_type="Middleware",
        name="L7 WebLogic",
        product_type="WebLogic",
        listen_address="wl.lab.example",
        listen_port=7001,
    )
    sync = client.post(
        "/api/monitor/targets/sync-from-cmdb", headers=auth_headers
    )
    assert sync.status_code == 200, sync.text
    targets = client.get(
        f"/api/monitor/targets?domain=middleware&component_id={mw}",
        headers=auth_headers,
    )
    assert targets.status_code == 200, targets.text
    target_id = targets.json()["items"][0]["target_id"]

    suggested = client.get(
        f"/api/monitor/targets/{target_id}/suggest-check",
        headers=auth_headers,
    )
    assert suggested.status_code == 200, suggested.text
    body = suggested.json()
    assert body["auto_create"] is False
    assert body["draft"] is not None
    draft = body["draft"]
    assert draft["target_id"] == target_id
    assert draft["component_id"] == mw
    assert draft["protocol"] == "tcp"
    assert draft["endpoint"]["host"] == "wl.lab.example"
    assert draft["endpoint"]["port"] == 7001
    assert body["cmdb_snapshot"]["product_type"] == "WebLogic"

    # Human save via checks API (does not run live).
    created = client.post(
        "/api/monitor/checks", headers=auth_headers, json=draft
    )
    assert created.status_code == 201, created.text
    assert created.json()["protocol"] == "tcp"
    assert created.json()["target_id"] == target_id


def test_suggest_check_empty_when_no_listen_fields(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    mw = _create_ci(
        client,
        auth_headers,
        component_type="Middleware",
        name="L7 No Listen",
        product_type="Tomcat",
    )
    sync = client.post(
        "/api/monitor/targets/sync-from-cmdb", headers=auth_headers
    )
    assert sync.status_code == 200, sync.text
    target_id = client.get(
        f"/api/monitor/targets?domain=middleware&component_id={mw}",
        headers=auth_headers,
    ).json()["items"][0]["target_id"]

    suggested = client.get(
        f"/api/monitor/targets/{target_id}/suggest-check",
        headers=auth_headers,
    )
    assert suggested.status_code == 200, suggested.text
    body = suggested.json()
    assert body["draft"] is None
    assert "listen_address" in (body.get("reason") or "")


def test_suggest_check_rejects_non_middleware(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    srv = _create_ci(
        client,
        auth_headers,
        component_type="Server",
        name="L7 Server Only",
        hostname="l7-srv.example",
        os_family="linux",
    )
    sync = client.post(
        "/api/monitor/targets/sync-from-cmdb", headers=auth_headers
    )
    assert sync.status_code == 200, sync.text
    target_id = client.get(
        f"/api/monitor/targets?domain=server&component_id={srv}",
        headers=auth_headers,
    ).json()["items"][0]["target_id"]

    suggested = client.get(
        f"/api/monitor/targets/{target_id}/suggest-check",
        headers=auth_headers,
    )
    assert suggested.status_code == 422, suggested.text


def test_meta_still_lists_middleware_domain(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    meta = client.get("/api/monitor/meta", headers=auth_headers)
    assert meta.status_code == 200, meta.text
    assert "middleware" in meta.json()["domains"]
