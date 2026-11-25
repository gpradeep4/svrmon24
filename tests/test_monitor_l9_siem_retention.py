"""Monitoring L9 — retention tiers + SIEM search + cold hooks (0.99.2)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import get_settings
from app.db import get_monitor_database
from app.services import entitlements as entitlements_service
from app.services import tenants as tenants_service
from app.tenancy import MIGRATION_TENANT_ID, stamp_tenant_id, tenant_filter
from tests.frontend_paths import FRONTEND_INDEX

MONITOR_LOGS_JS = Path("frontend/static/js/monitor/logs.js")


def test_version_bump_for_monitor_l9() -> None:
    assert __version__ == "0.99.2"
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.2"' in html
    assert "monitor/logs.js?v=0.99.2" in html
    assert 'id="mlAttr"' in html
    assert 'id="mlLoadMore"' in html
    assert 'id="mlRetentionBadge"' in html
    assert 'multiple' in html.split('id="mlSeverity"', 1)[1][:200]

    logs_js = MONITOR_LOGS_JS.read_text(encoding="utf-8")
    assert "next_cursor" in logs_js
    assert "retention_tier" in logs_js
    assert "mlAttr" in logs_js
    assert "Load more" in html or "mlLoadMore" in logs_js

    assert Path("app/monitor/services/cold_storage.py").is_file()
    assert Path("app/monitor/services/retention.py").is_file()


def test_retention_days_entitlements_catalog() -> None:
    plans = {p["plan_code"]: p["limits"] for p in entitlements_service.list_plans()}
    starter = plans["starter"]
    standard = plans["standard"]
    unlimited = plans["legacy_unlimited"]
    assert starter["monitor_retention_days_hot"] == 7
    assert starter["monitor_retention_days_extended"] == 0
    assert starter["monitor_retention_days_siem"] == 0
    assert standard["monitor_retention_days_hot"] == 30
    assert standard["monitor_retention_days_extended"] == 90
    assert standard["monitor_retention_days_siem"] == 0
    assert unlimited["monitor_retention_days_hot"] is None
    assert unlimited["monitor_retention_days_extended"] is None
    assert unlimited["monitor_retention_days_siem"] is None


def test_retention_tier_locked_for_starter(
    client: TestClient, auth_headers: dict[str, str], clean_db, monkeypatch
) -> None:
    tenants_service.ensure_migration_tenant()
    monkeypatch.setattr(
        entitlements_service,
        "_plan_for_tenant",
        lambda _tid: entitlements_service.get_plan("starter"),
    )
    locked = client.patch(
        "/api/monitor/admin/live-settings",
        headers=auth_headers,
        json={"monitor_retention_tier": "extended"},
    )
    assert locked.status_code == 403, locked.text
    body = locked.json()
    detail = body.get("detail") or (body.get("error") or {}).get("message") or ""
    assert "locked" in str(detail).lower()

    ok = client.patch(
        "/api/monitor/admin/live-settings",
        headers=auth_headers,
        json={"monitor_retention_tier": "hot"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["tenant"]["monitor_retention_tier"] == "hot"


def test_retention_sweep_deletes_by_wall_clock_days(
    client: TestClient, auth_headers: dict[str, str], clean_db, monkeypatch
) -> None:
    tenants_service.ensure_migration_tenant()
    tenant_id = MIGRATION_TENANT_ID
    monkeypatch.setattr(
        entitlements_service, "effective_monitor_retention_days", lambda _tid: 7
    )
    monkeypatch.setattr(
        entitlements_service, "log_events_retained_limit", lambda _tid: None
    )
    monkeypatch.setattr(
        entitlements_service, "metric_samples_retained_limit", lambda _tid: None
    )

    events = get_monitor_database()["log_events"]
    now = datetime.now(timezone.utc)
    for i, age_days in enumerate((1, 3, 10, 20)):
        events.insert_one(
            stamp_tenant_id(
                {
                    "event_id": f"le-l9-age-{i}",
                    "stream_id": "ls-l9",
                    "severity": "info",
                    "message": f"aged event {age_days}d",
                    "attrs": {"demo": True},
                    "observed_at": now - timedelta(days=age_days),
                    "data_source": "SYNTHETIC_DEMO",
                    "execution_mode": "SIMULATED",
                    "source": "simulated",
                    "created_at": now,
                },
                tenant_id=tenant_id,
            )
        )

    sweep = client.post(
        "/api/monitor/admin/retention-sweep", headers=auth_headers
    )
    assert sweep.status_code == 200, sweep.text
    body = sweep.json()
    assert body["retention_days"] == 7
    assert body["log_events_trimmed_by_age"] >= 2
    remaining = list(events.find(tenant_filter(tenant_id)))
    assert len(remaining) == 2
    ages = {
        (now - row["observed_at"]).days
        if row["observed_at"].tzinfo
        else (now.replace(tzinfo=None) - row["observed_at"]).days
        for row in remaining
    }
    assert ages <= {1, 2, 3}


def test_logs_search_phrase_severity_attrs_and_cursor(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    tenants_service.ensure_migration_tenant()
    tenant_id = MIGRATION_TENANT_ID
    events = get_monitor_database()["log_events"]
    now = datetime.now(timezone.utc)
    rows = [
        ("le-l9-1", "error", "Upstream timeout connecting to redis", {"env": "prod", "svc": "api"}),
        ("le-l9-2", "warning", "Elevated latency detected", {"env": "prod", "svc": "api"}),
        ("le-l9-3", "error", "Upstream timeout connecting to redis", {"env": "dev", "svc": "api"}),
        ("le-l9-4", "info", "Heartbeat OK", {"env": "prod", "svc": "worker"}),
        ("le-l9-5", "critical", "Health check failed", {"env": "prod", "svc": "api"}),
    ]
    for idx, (eid, sev, msg, attrs) in enumerate(rows):
        events.insert_one(
            stamp_tenant_id(
                {
                    "event_id": eid,
                    "stream_id": "ls-l9-search",
                    "severity": sev,
                    "message": msg,
                    "attrs": attrs,
                    "observed_at": now - timedelta(seconds=idx),
                    "data_source": "SYNTHETIC_DEMO",
                    "execution_mode": "SIMULATED",
                    "source": "simulated",
                    "created_at": now,
                },
                tenant_id=tenant_id,
            )
        )

    phrase = client.get(
        '/api/monitor/logs/events?q=%22Upstream%20timeout%20connecting%20to%20redis%22',
        headers=auth_headers,
    )
    assert phrase.status_code == 200, phrase.text
    phrase_body = phrase.json()
    assert phrase_body["total"] == 2
    assert all(
        "Upstream timeout connecting to redis" in (item["message"] or "")
        for item in phrase_body["items"]
    )

    multi = client.get(
        "/api/monitor/logs/events?severity=error,critical&attr=env:prod",
        headers=auth_headers,
    )
    assert multi.status_code == 200, multi.text
    multi_body = multi.json()
    assert multi_body["total"] == 2
    ids = {item["event_id"] for item in multi_body["items"]}
    assert ids == {"le-l9-1", "le-l9-5"}

    page1 = client.get(
        "/api/monitor/logs/events?page_size=2&sort_dir=desc",
        headers=auth_headers,
    )
    assert page1.status_code == 200, page1.text
    p1 = page1.json()
    assert len(p1["items"]) == 2
    assert p1["next_cursor"]
    page2 = client.get(
        f"/api/monitor/logs/events?page_size=2&cursor={p1['next_cursor']}",
        headers=auth_headers,
    )
    assert page2.status_code == 200, page2.text
    p2 = page2.json()
    assert len(p2["items"]) == 2
    overlap = {i["event_id"] for i in p1["items"]} & {
        i["event_id"] for i in p2["items"]
    }
    assert not overlap


def test_cold_archive_noop_when_uri_empty(
    client: TestClient, auth_headers: dict[str, str], clean_db, monkeypatch
) -> None:
    tenants_service.ensure_migration_tenant()
    monkeypatch.setenv("MONITOR_COLD_STORAGE_URI", "")
    get_settings.cache_clear()
    try:
        resp = client.post(
            "/api/monitor/admin/cold-archive", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["archived"] is False
        assert body["reason"] == "cold storage not configured"
        assert body["status"] == "noop"
        meta = client.get("/api/monitor/meta", headers=auth_headers)
        assert meta.status_code == 200
        assert meta.json()["cold_archive"] == "/api/monitor/admin/cold-archive"
        assert meta.json()["cold_storage"]["configured"] is False
    finally:
        get_settings.cache_clear()


def test_cold_archive_file_adapter_writes_manifest(
    client: TestClient,
    auth_headers: dict[str, str],
    clean_db,
    monkeypatch,
    tmp_path: Path,
) -> None:
    tenants_service.ensure_migration_tenant()
    tenant_id = MIGRATION_TENANT_ID
    cold_root = tmp_path / "cold"
    monkeypatch.setenv("MONITOR_COLD_STORAGE_URI", f"file://{cold_root}")
    get_settings.cache_clear()
    try:
        events = get_monitor_database()["log_events"]
        now = datetime.now(timezone.utc)
        for i in range(3):
            events.insert_one(
                stamp_tenant_id(
                    {
                        "event_id": f"le-l9-cold-{i}",
                        "stream_id": "ls-cold",
                        "severity": "warning",
                        "message": f"cold candidate {i}",
                        "attrs": {"batch": "l9"},
                        "observed_at": now - timedelta(days=30 + i),
                        "data_source": "SYNTHETIC_DEMO",
                        "execution_mode": "SIMULATED",
                        "source": "simulated",
                        "created_at": now,
                    },
                    tenant_id=tenant_id,
                )
            )
        # Fresh event should not be archived with older_than_days=7.
        events.insert_one(
            stamp_tenant_id(
                {
                    "event_id": "le-l9-cold-fresh",
                    "stream_id": "ls-cold",
                    "severity": "info",
                    "message": "fresh",
                    "attrs": {},
                    "observed_at": now - timedelta(hours=1),
                    "data_source": "SYNTHETIC_DEMO",
                    "execution_mode": "SIMULATED",
                    "source": "simulated",
                    "created_at": now,
                },
                tenant_id=tenant_id,
            )
        )

        resp = client.post(
            "/api/monitor/admin/cold-archive?older_than_days=7&limit=100",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["archived"] is True
        assert body["event_count"] == 3
        assert body["scheme"] == "file"
        manifest_path = Path(body["manifest_path"])
        events_path = Path(body["events_path"])
        assert manifest_path.is_file()
        assert events_path.is_file()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["event_count"] == 3
        assert manifest["adapter"] == "file"
        lines = [
            ln for ln in events_path.read_text(encoding="utf-8").splitlines() if ln
        ]
        assert len(lines) == 3
        # Hot Mongo rows remain (archive does not delete).
        assert events.count_documents(tenant_filter(tenant_id)) == 4

        jobs = client.get(
            "/api/monitor/admin/retention-jobs", headers=auth_headers
        )
        assert jobs.status_code == 200, jobs.text
        assert jobs.json()["total"] >= 1
        assert jobs.json()["items"][0]["status"] == "completed"
    finally:
        get_settings.cache_clear()


def test_meta_exposes_retention_and_cold_paths(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    tenants_service.ensure_migration_tenant()
    meta = client.get("/api/monitor/meta", headers=auth_headers)
    assert meta.status_code == 200, meta.text
    body = meta.json()
    assert body["retention_tier"] == "hot"
    assert "retention_days_by_tier" in body
    assert body["cold_archive"] == "/api/monitor/admin/cold-archive"
    assert body["retention_jobs"] == "/api/monitor/admin/retention-jobs"
    assert "cold_storage" in body
