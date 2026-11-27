"""Monitoring M6 — SIMULATED alert rules + instances (0.99.10)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from tests.frontend_paths import FRONTEND_INDEX

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


def test_version_bump_for_monitor_m6() -> None:
    assert __version__ == "0.99.10"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.10"' in html
    assert "monitor/alerts.js?v=0.99.10" in html
    assert "monitor/index.js?v=0.99.10" in html


def test_alerts_ui_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'id="tab-monitor-alerts"' in html
    assert 'id="maInstancesBody"' in html
    assert 'id="maRulesBody"' in html
    assert 'id="maEvaluate"' in html
    assert 'id="maCreateRule"' in html
    # Default remains off; L8 adds opt-in auto-create (banner still says OFF).
    alerts_panel = html.split('id="tab-monitor-alerts"')[1].split(
        'id="tab-itsm-dashboard"'
    )[0]
    assert (
        "No auto-incident" in alerts_panel
        or "no auto-incident" in alerts_panel.lower()
        or "Auto-create ITSM incidents is" in alerts_panel
    )
    assert "OFF" in alerts_panel or "no auto-incident" in alerts_panel.lower()
    assert "placeholder-panel" not in html.split('id="tab-monitor-alerts"')[1].split(
        'id="tab-itsm-dashboard"'
    )[0]
    js = MONITOR_ALERTS_JS.read_text(encoding="utf-8")
    assert "/api/monitor/alerts/rules" in js
    assert "/api/monitor/alerts/instances" in js
    assert "/ack" in js
    assert "/resolve" in js
    assert "monitor:alerts:write" in js
    idx = MONITOR_INDEX_JS.read_text(encoding="utf-8")
    assert "SVRMON24MonitorAlerts" in idx
    cmdb = Path("frontend/static/js/cmdb.js").read_text(encoding="utf-8")
    assert "SVRMON24MonitorAlerts?.onShowTab" in cmdb or "SVRMON24MonitorAlerts.onShowTab" in cmdb


def test_alert_rules_crud_evaluate_ack_resolve(
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
        name="M6 Alert Host",
        hostname="m6-alert.example",
        os_family="linux",
    )
    sync = client.post(
        "/api/monitor/targets/sync-from-cmdb", headers=auth_headers
    )
    assert sync.status_code == 200, sync.text

    # Default rules seed on list.
    rules = client.get("/api/monitor/alerts/rules", headers=auth_headers)
    assert rules.status_code == 200, rules.text
    body = rules.json()
    assert body["total"] >= 1
    assert body["execution_mode"] == "SIMULATED"
    assert body["live_probes"] is False
    assert any(
        (r.get("condition") or {}).get("type") == "log_match"
        for r in body["items"]
    )

    # Create an explicit low-threshold rule so evaluate always fires.
    created = client.post(
        "/api/monitor/alerts/rules",
        headers=auth_headers,
        json={
            "name": "M6 always-fire CPU",
            "severity": "warning",
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
    rule = created.json()
    assert rule["rule_id"].startswith("ar-")
    assert rule["condition"]["type"] == "threshold"

    # Audit on rule create
    from app.db import get_database

    audits = list(
        get_database()["audit_events"].find(
            {
                "tenant_id": MIGRATION_TENANT_ID,
                "action": "monitor.alerts.rule_create",
                "resource_id": rule["rule_id"],
            }
        )
    )
    assert len(audits) >= 1

    # Simulate tick → log events + alert evaluation
    tick = client.post(
        "/api/monitor/logs/simulate-tick?events_per_stream=3",
        headers=auth_headers,
    )
    assert tick.status_code == 200, tick.text
    assert tick.json().get("alert_rules_evaluated", 0) >= 1

    # Explicit evaluate
    ev = client.post("/api/monitor/alerts/evaluate", headers=auth_headers)
    assert ev.status_code == 200, ev.text
    assert ev.json()["execution_mode"] == "SIMULATED"
    assert ev.json()["live_probes"] is False

    instances = client.get(
        "/api/monitor/alerts/instances?status=firing,acked",
        headers=auth_headers,
    )
    assert instances.status_code == 200, instances.text
    payload = instances.json()
    assert payload["total"] >= 1
    assert payload["open_count"] >= 1
    alert = payload["items"][0]
    alert_id = alert["alert_id"]
    assert alert["status"] in {"firing", "acked"}
    assert alert.get("suggested_incident_id") is None

    # Ack
    if alert["status"] == "firing":
        ack = client.post(
            f"/api/monitor/alerts/instances/{alert_id}/ack",
            headers=auth_headers,
        )
        assert ack.status_code == 200, ack.text
        assert ack.json()["status"] == "acked"

    # Resolve
    resolved = client.post(
        f"/api/monitor/alerts/instances/{alert_id}/resolve",
        headers=auth_headers,
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"

    # Patch disable rule
    patched = client.patch(
        f"/api/monitor/alerts/rules/{rule['rule_id']}",
        headers=auth_headers,
        json={"enabled": False},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["enabled"] is False

    monitor = get_monitor_database()
    filt = tenant_filter(MIGRATION_TENANT_ID)
    assert monitor["alert_rules"].count_documents(filt) >= 1
    assert monitor["alert_instances"].count_documents(filt) >= 1


def test_alert_rules_write_requires_permission(
    client: TestClient, auth_headers: dict[str, str], clean_db, monkeypatch
) -> None:
    from fastapi import HTTPException

    from app.permissions import PERM_MONITOR_ALERTS_WRITE
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()

    # Ensure read still works with defaults
    listed = client.get("/api/monitor/alerts/rules", headers=auth_headers)
    assert listed.status_code == 200, listed.text

    def deny_write(tenant, permission: str, *args, **kwargs):
        if permission == PERM_MONITOR_ALERTS_WRITE:
            raise HTTPException(
                status_code=403,
                detail=f"Missing permission: {PERM_MONITOR_ALERTS_WRITE}",
            )
        return None

    monkeypatch.setattr("app.permissions.assert_permission", deny_write)

    denied = client.post(
        "/api/monitor/alerts/rules",
        headers=auth_headers,
        json={
            "name": "denied",
            "condition": {"type": "log_match", "severity": "error"},
        },
    )
    assert denied.status_code == 403, denied.text

    denied_eval = client.post(
        "/api/monitor/alerts/evaluate", headers=auth_headers
    )
    assert denied_eval.status_code == 403, denied_eval.text


def test_alert_rules_entitlement_enforced(
    client: TestClient, auth_headers: dict[str, str], clean_db, monkeypatch
) -> None:
    from app.services import entitlements as entitlements_service
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    # Seed defaults first (will consume slots under limit).
    listed = client.get("/api/monitor/alerts/rules", headers=auth_headers)
    assert listed.status_code == 200
    existing = listed.json()["total"]

    monkeypatch.setattr(
        entitlements_service, "alert_rules_limit", lambda _tid: existing
    )

    blocked = client.post(
        "/api/monitor/alerts/rules",
        headers=auth_headers,
        json={
            "name": "over limit",
            "condition": {"type": "log_match", "severity": "critical"},
        },
    )
    assert blocked.status_code == 403, blocked.text
    detail = str(
        blocked.json().get("detail")
        or (blocked.json().get("error") or {}).get("message")
        or blocked.json()
    )
    assert "limit" in detail.lower()


def test_alert_instances_tenant_isolation(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from datetime import datetime, timezone

    from app.db import get_database, get_monitor_database
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    # Ensure our tenant has at least one evaluate pass.
    client.get("/api/monitor/alerts/rules", headers=auth_headers)
    client.post("/api/monitor/alerts/evaluate", headers=auth_headers)

    other_id = "tenant-m6-other"
    now = datetime.now(timezone.utc)
    get_database()["tenants"].update_one(
        {"tenant_id": other_id},
        {
            "$setOnInsert": {
                "tenant_id": other_id,
                "display_name": "M6 Other",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    get_monitor_database()["alert_instances"].insert_one(
        {
            "alert_id": "al-other-secret",
            "rule_id": "ar-other",
            "rule_name": "Secret rule",
            "component_id": "srv-secret",
            "fingerprint": "ar-other:srv-secret:_",
            "status": "firing",
            "severity": "critical",
            "summary": "SECRET cross-tenant alert",
            "evidence_refs": [],
            "suggested_incident_id": None,
            "fired_at": now,
            "execution_mode": "SIMULATED",
            "data_source": "SYNTHETIC_DEMO",
            "tenant_id": other_id,
            "created_at": now,
            "updated_at": now,
        }
    )

    listed = client.get("/api/monitor/alerts/instances", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    ids = {a["alert_id"] for a in listed.json()["items"]}
    assert "al-other-secret" not in ids
    summaries = " ".join(
        a.get("summary") or "" for a in listed.json()["items"]
    )
    assert "SECRET cross-tenant" not in summaries


def test_meta_includes_alert_taxonomy(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    meta = client.get("/api/monitor/meta", headers=auth_headers)
    assert meta.status_code == 200, meta.text
    body = meta.json()
    assert body["live_probes"] is False
    assert "threshold" in body.get("alert_condition_types", [])
    assert "firing" in body.get("alert_statuses", [])
    assert "no auto-incident" in (body.get("notice") or "").lower() or (
        "auto-incident" in (body.get("notice") or "").lower()
    )
