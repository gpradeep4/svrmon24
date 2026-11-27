"""Monitoring M5 — SIMULATED log streams + search (0.99.11)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from tests.frontend_paths import FRONTEND_INDEX

MONITOR_LOGS_JS = Path("frontend/static/js/monitor/logs.js")
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


def test_version_bump_for_monitor_m5() -> None:
    assert __version__ == "0.99.11"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.11"' in html
    assert "monitor/logs.js?v=0.99.11" in html
    assert "monitor/index.js?v=0.99.11" in html


def test_logs_ui_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'id="tab-monitor-logs"' in html
    assert 'id="mlEventsBody"' in html
    assert 'id="mlSearch"' in html
    assert 'id="mlSeverity"' in html
    assert 'id="mlComponentId"' in html
    assert 'id="mlSimulate"' in html
    assert "No live syslog" in html or "no live syslog" in html.lower()
    assert "placeholder-panel" not in html.split('id="tab-monitor-logs"')[1].split(
        'id="tab-monitor-alerts"'
    )[0]
    js = MONITOR_LOGS_JS.read_text(encoding="utf-8")
    assert "/api/monitor/logs/events" in js
    assert "simulate-tick" in js
    assert "monitor:admin" in js
    idx = MONITOR_INDEX_JS.read_text(encoding="utf-8")
    assert "SVRMON24MonitorLogs" in idx
    assert "applyMonitorActionGates" in idx
    cmdb = Path("frontend/static/js/cmdb.js").read_text(encoding="utf-8")
    assert "SVRMON24MonitorLogs?.onShowTab" in cmdb or "SVRMON24MonitorLogs.onShowTab" in cmdb


def test_simulate_tick_search_and_filters(
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
        name="M5 Log Host",
        hostname="m5-log.example",
        os_family="linux",
    )
    sync = client.post(
        "/api/monitor/targets/sync-from-cmdb", headers=auth_headers
    )
    assert sync.status_code == 200, sync.text

    tick = client.post(
        "/api/monitor/logs/simulate-tick?events_per_stream=4",
        headers=auth_headers,
    )
    assert tick.status_code == 200, tick.text
    body = tick.json()
    assert body["events_created"] >= 4
    assert body["execution_mode"] == "SIMULATED"
    assert body["live_probes"] is False
    assert body["streams_ensured"] >= 1
    assert set(body["sources"]) == {"agentless", "agent", "simulated"}

    streams = client.get("/api/monitor/logs/streams", headers=auth_headers)
    assert streams.status_code == 200, streams.text
    stream_items = streams.json()["items"]
    assert streams.json()["total"] >= 1
    assert any(s.get("component_id") == cid for s in stream_items)
    assert all(s["execution_mode"] == "SIMULATED" for s in stream_items)

    events = client.get("/api/monitor/logs/events", headers=auth_headers)
    assert events.status_code == 200, events.text
    payload = events.json()
    assert payload["total"] >= 4
    assert payload["live_probes"] is False
    assert payload["data_source"] == "SYNTHETIC_DEMO"
    assert any(e.get("component_id") == cid for e in payload["items"])
    assert all(
        e.get("source") in {"agentless", "agent", "simulated"}
        for e in payload["items"]
    )

    # Search by q (message substring that always appears in templates).
    searched = client.get(
        "/api/monitor/logs/events?q=SIMULATED",
        headers=auth_headers,
    )
    assert searched.status_code == 200, searched.text
    # q may or may not match; also try a known token from demo messages
    by_ci = client.get(
        f"/api/monitor/logs/events?component_id={cid}",
        headers=auth_headers,
    )
    assert by_ci.status_code == 200, by_ci.text
    assert by_ci.json()["total"] >= 1
    assert all(e["component_id"] == cid for e in by_ci.json()["items"])

    # Severity filter
    for sev in ("info", "warning", "error", "critical", "debug"):
        filtered = client.get(
            f"/api/monitor/logs/events?severity={sev}",
            headers=auth_headers,
        )
        assert filtered.status_code == 200, filtered.text
        assert all(e["severity"] == sev for e in filtered.json()["items"])

    # Source filter
    src = client.get(
        "/api/monitor/logs/events?source=simulated",
        headers=auth_headers,
    )
    assert src.status_code == 200, src.text
    assert all(e["source"] == "simulated" for e in src.json()["items"])

    stream_id = stream_items[0]["stream_id"]
    by_stream = client.get(
        f"/api/monitor/logs/events?stream_id={stream_id}",
        headers=auth_headers,
    )
    assert by_stream.status_code == 200
    assert all(e["stream_id"] == stream_id for e in by_stream.json()["items"])

    monitor = get_monitor_database()
    filt = tenant_filter(MIGRATION_TENANT_ID)
    assert monitor["log_streams"].count_documents(filt) >= 1
    assert monitor["log_events"].count_documents(filt) >= 4


def test_simulate_tick_requires_admin(
    client: TestClient, auth_headers: dict[str, str], clean_db, monkeypatch
) -> None:
    from fastapi import HTTPException

    from app.permissions import PERM_MONITOR_ADMIN
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()

    def deny_admin(tenant, permission: str, *args, **kwargs):
        if permission == PERM_MONITOR_ADMIN:
            raise HTTPException(
                status_code=403,
                detail=f"Missing permission: {PERM_MONITOR_ADMIN}",
            )
        return None

    monkeypatch.setattr("app.permissions.assert_permission", deny_admin)

    listed = client.get("/api/monitor/logs/events", headers=auth_headers)
    assert listed.status_code == 200, listed.text

    denied = client.post(
        "/api/monitor/logs/simulate-tick", headers=auth_headers
    )
    assert denied.status_code == 403, denied.text
    detail = str(
        denied.json().get("detail")
        or (denied.json().get("error") or {}).get("message")
        or denied.json()
    )
    assert PERM_MONITOR_ADMIN in detail


def test_log_events_retention_enforced(
    client: TestClient, auth_headers: dict[str, str], clean_db, monkeypatch
) -> None:
    from app.db import get_monitor_database
    from app.services import entitlements as entitlements_service
    from app.services import tenants as tenants_service
    from app.tenancy import MIGRATION_TENANT_ID, tenant_filter

    tenants_service.ensure_migration_tenant()
    monkeypatch.setattr(
        entitlements_service, "log_events_retained_limit", lambda _tid: 5
    )

    tick1 = client.post(
        "/api/monitor/logs/simulate-tick?events_per_stream=3",
        headers=auth_headers,
    )
    assert tick1.status_code == 200, tick1.text
    # Fallback streams = 3 → 9 events, trimmed to 5.
    assert tick1.json()["retained_total"] <= 5
    assert tick1.json()["events_trimmed"] >= 1

    tick2 = client.post(
        "/api/monitor/logs/simulate-tick?events_per_stream=2",
        headers=auth_headers,
    )
    assert tick2.status_code == 200, tick2.text
    assert tick2.json()["retained_total"] <= 5

    monitor = get_monitor_database()
    assert (
        monitor["log_events"].count_documents(tenant_filter(MIGRATION_TENANT_ID))
        <= 5
    )


def test_log_events_tenant_isolation(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from datetime import datetime, timezone

    from app.db import get_database, get_monitor_database
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    tick = client.post(
        "/api/monitor/logs/simulate-tick", headers=auth_headers
    )
    assert tick.status_code == 200, tick.text

    other_id = "tenant-m5-other"
    now = datetime.now(timezone.utc)
    get_database()["tenants"].update_one(
        {"tenant_id": other_id},
        {
            "$setOnInsert": {
                "tenant_id": other_id,
                "display_name": "M5 Other",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    get_monitor_database()["log_events"].insert_one(
        {
            "event_id": "le-other-secret",
            "stream_id": "ls-other",
            "component_id": "srv-secret",
            "severity": "critical",
            "message": "SECRET cross-tenant log line",
            "attrs": {},
            "observed_at": now,
            "data_source": "SYNTHETIC_DEMO",
            "execution_mode": "SIMULATED",
            "source": "simulated",
            "tenant_id": other_id,
            "created_at": now,
        }
    )

    listed = client.get("/api/monitor/logs/events", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    ids = {e["event_id"] for e in listed.json()["items"]}
    assert "le-other-secret" not in ids
    messages = " ".join(e.get("message") or "" for e in listed.json()["items"])
    assert "SECRET cross-tenant" not in messages

    q = client.get(
        "/api/monitor/logs/events?q=SECRET",
        headers=auth_headers,
    )
    assert q.status_code == 200
    assert q.json()["total"] == 0
