"""ITSM N3 scheduled report delivery — CRUD, tick email, disable, isolation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app import __version__
from app.db import get_itsm_database
from app.itsm.services import jobs as jobs_service
from app.itsm.services import notification_channels as channel_settings_service
from app.itsm.services import report_schedules as schedules_service
from app.itsm.services.jobs import JOB_REPORT_SCHEDULES
from app.itsm.services.notification_providers import (
    DeliveryResult,
    set_email_provider_for_tests,
)
from app.tenancy import MIGRATION_TENANT_ID
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_report_schedules_slice() -> None:
    assert __version__ == "0.66.0"


@dataclass
class _CapturingEmail:
    channel: str = "email"
    calls: list = field(default_factory=list)

    def deliver(self, *, recipient_address, subject, body, channel_config, attachments=None):
        self.calls.append(
            {
                "recipient_address": recipient_address,
                "subject": subject,
                "body": body,
                "attachments": attachments or [],
            }
        )
        return DeliveryResult(
            status="sent",
            provider="smtp_fake",
            recipient_address=recipient_address,
        )


def _enable_email(tenant_id: str) -> None:
    channel_settings_service.upsert_channel_settings(
        tenant_id=tenant_id,
        channel="email",
        payload={
            "enabled": True,
            "smtp_host": "smtp.test.local",
            "from_address": "itsm@example.com",
            "smtp_password_env_ref": "ITSM_SMTP_PASSWORD",
        },
        actor={"user_id": "admin", "username": "admin"},
    )


def _create_report(client: TestClient, auth_headers: dict[str, str]) -> dict:
    resp = client.post(
        "/api/itsm/reports/definitions",
        headers=auth_headers,
        json={
            "name": "Open INC digest",
            "metrics": ["open_incidents", "ticket_rows"],
            "filters": {"window_days": 30, "ticket_types": ["incident"]},
            "columns": ["ticket_id", "title", "status", "priority"],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_schedule_create_forced_tick_delivers_email(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    fake = _CapturingEmail()
    set_email_provider_for_tests(fake)
    try:
        report = _create_report(client, auth_headers)
        tid = report["tenant_id"]
        _enable_email(tid)

        created = client.post(
            "/api/itsm/reports/schedules",
            headers=auth_headers,
            json={
                "report_id": report["report_id"],
                "name": "Daily ops digest",
                "interval_minutes": 60,
                "timezone": "UTC",
                "recipients": ["ops@example.com", "cab@example.com"],
                "channels": ["email"],
                "format": "csv",
                "active": True,
            },
        )
        assert created.status_code == 201, created.text
        schedule = created.json()
        schedule_id = schedule["schedule_id"]
        assert schedule["active"] is True
        assert schedule["next_run_at"] is not None

        # Force due: set next_run_at in the past, then job tick.
        get_itsm_database()["itsm_report_schedules"].update_one(
            {"schedule_id": schedule_id},
            {
                "$set": {
                    "next_run_at": datetime.now(timezone.utc) - timedelta(minutes=1)
                }
            },
        )

        tick = jobs_service.run_tick(
            tenant_id=tid,
            jobs=[JOB_REPORT_SCHEDULES],
            force=True,
        )
        assert tick["ok"] is True
        job = tick["jobs"][JOB_REPORT_SCHEDULES]
        assert job.get("placeholder") is False
        assert job["ran"] >= 1
        assert job["sent"] >= 1
        assert len(fake.calls) >= 2  # one per recipient
        assert all(c["attachments"] for c in fake.calls)
        assert fake.calls[0]["attachments"][0]["filename"].endswith(".csv")

        runs = client.get(
            f"/api/itsm/reports/schedules/runs?schedule_id={schedule_id}",
            headers=auth_headers,
        )
        assert runs.status_code == 200, runs.text
        assert runs.json()["total"] >= 1
        assert runs.json()["items"][0]["status"] == "sent"

        # Run-now API also works.
        forced = client.post(
            f"/api/itsm/reports/schedules/{schedule_id}/run",
            headers=auth_headers,
        )
        assert forced.status_code == 200, forced.text
        assert forced.json()["status"] == "sent"
    finally:
        set_email_provider_for_tests(None)


def test_disable_schedule_stops_sends(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    fake = _CapturingEmail()
    set_email_provider_for_tests(fake)
    try:
        report = _create_report(client, auth_headers)
        tid = report["tenant_id"]
        _enable_email(tid)
        created = client.post(
            "/api/itsm/reports/schedules",
            headers=auth_headers,
            json={
                "report_id": report["report_id"],
                "interval_minutes": 60,
                "recipients": ["ops@example.com"],
                "format": "xlsx",
                "active": True,
            },
        )
        assert created.status_code == 201, created.text
        schedule_id = created.json()["schedule_id"]

        disabled = client.patch(
            f"/api/itsm/reports/schedules/{schedule_id}",
            headers=auth_headers,
            json={"active": False},
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["active"] is False
        assert disabled.json()["next_run_at"] is None

        get_itsm_database()["itsm_report_schedules"].update_one(
            {"schedule_id": schedule_id},
            {
                "$set": {
                    "next_run_at": datetime.now(timezone.utc) - timedelta(minutes=1),
                    "active": False,
                }
            },
        )
        result = schedules_service.run_due_schedules(tenant_id=tid)
        assert result["ran"] == 0
        assert fake.calls == []
    finally:
        set_email_provider_for_tests(None)


def test_schedule_tenant_isolation(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    report = _create_report(client, auth_headers)
    created = client.post(
        "/api/itsm/reports/schedules",
        headers=auth_headers,
        json={
            "report_id": report["report_id"],
            "interval_minutes": 1440,
            "recipients": ["ops@example.com"],
            "active": True,
        },
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["schedule_id"]

    foreign = dict(
        get_itsm_database()["itsm_report_schedules"].find_one(
            {"schedule_id": schedule_id}
        )
    )
    foreign.pop("_id", None)
    foreign["tenant_id"] = "tenant-other-org"
    foreign["schedule_id"] = "RSCH-FOREIGN01"
    get_itsm_database()["itsm_report_schedules"].insert_one(foreign)

    missing = client.get(
        "/api/itsm/reports/schedules/RSCH-FOREIGN01", headers=auth_headers
    )
    assert missing.status_code == 404

    own = client.get(
        f"/api/itsm/reports/schedules/{schedule_id}", headers=auth_headers
    )
    assert own.status_code == 200
    assert own.json()["tenant_id"] == MIGRATION_TENANT_ID

    listed = client.get("/api/itsm/reports/schedules", headers=auth_headers)
    assert listed.status_code == 200
    assert all(row["tenant_id"] == MIGRATION_TENANT_ID for row in listed.json()["items"])
    assert all(row["schedule_id"] != "RSCH-FOREIGN01" for row in listed.json()["items"])


def test_frontend_schedule_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.66.0"' in html
    assert 'id="itsmReportSchedulesSection"' in html
    assert 'id="itsmReportScheduleTable"' in html
    assert "itsm/reports.js?v=0.66.0" in html
