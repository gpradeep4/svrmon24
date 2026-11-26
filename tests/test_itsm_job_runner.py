"""ITSM N2 job runner — SLA sweeper, delivery retries, leases (0.64.0)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import __version__
from app.config import get_settings
from app.db import get_itsm_database
from app.itsm.services import jobs as jobs_service
from app.itsm.services import notification_channels as channel_settings_service
from app.itsm.services import notification_delivery as delivery_service
from app.itsm.services.jobs import (
    JOB_DELIVERY_RETRIES,
    JOB_REPORT_SCHEDULES,
    JOB_SLA_SWEEPER,
)
from app.itsm.services.notification_providers import (
    DeliveryResult,
    set_email_provider_for_tests,
)
from app.permissions import (
    ALL_PERMISSIONS,
    PERM_ITSM_JOBS_ADMIN,
    permissions_for_role,
)
from app.tenancy import MEMBERSHIP_ROLE_ADMIN, MEMBERSHIP_ROLE_VIEWER, MIGRATION_TENANT_ID
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_job_runner_slice() -> None:
    assert __version__ == "0.99.7"


def test_jobs_admin_permission_in_catalog() -> None:
    assert PERM_ITSM_JOBS_ADMIN in ALL_PERMISSIONS
    assert PERM_ITSM_JOBS_ADMIN in permissions_for_role(MEMBERSHIP_ROLE_ADMIN)
    assert PERM_ITSM_JOBS_ADMIN not in permissions_for_role(MEMBERSHIP_ROLE_VIEWER)


def test_job_runner_disabled_by_default() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.itsm_job_runner_enabled is False


def test_sla_sweeper_breaches_without_ui_and_is_idempotent(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    # Create incident so assignee lookup works for breach notify.
    created = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "Overdue sweeper",
            "description": "past due",
            "priority": "p1",
            "category": "network",
        },
    )
    assert created.status_code == 201, created.text
    incident = created.json()
    tid = incident["tenant_id"]
    incident_id = incident["incident_id"]
    client.patch(
        f"/api/itsm/incidents/{incident_id}",
        headers=auth_headers,
        json={"assignee_user_id": "testuser"},
    )

    itsm = get_itsm_database()
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    tracking_id = "SLA-SWEEP001"
    itsm["itsm_sla_tracking"].insert_one(
        {
            "tenant_id": tid,
            "tracking_id": tracking_id,
            "policy_id": "SLA-POL-SWEEP",
            "ticket_type": "incident",
            "ticket_id": incident_id,
            "metric": "response",
            "status": "running",
            "due_at": past,
            "started_at": past - timedelta(hours=1),
            "created_at": past,
            "updated_at": past,
        }
    )

    # Foreign tenant overdue row must not be touched when scoped.
    itsm["itsm_sla_tracking"].insert_one(
        {
            "tenant_id": "tenant-other-org",
            "tracking_id": "SLA-OTHER001",
            "policy_id": "SLA-POL-OTHER",
            "ticket_type": "incident",
            "ticket_id": "INC-OTHER",
            "metric": "response",
            "status": "running",
            "due_at": past,
            "started_at": past - timedelta(hours=1),
            "created_at": past,
            "updated_at": past,
        }
    )

    first = jobs_service.sweep_sla_overdue(tenant_id=tid)
    assert first["scanned"] >= 1
    assert first["breached"] >= 1
    doc = itsm["itsm_sla_tracking"].find_one({"tracking_id": tracking_id})
    assert doc["status"] == "breached"
    foreign = itsm["itsm_sla_tracking"].find_one({"tracking_id": "SLA-OTHER001"})
    assert foreign["status"] == "running"

    # Breach notify landed for assignee inbox.
    assert (
        itsm["itsm_notifications"].count_documents(
            {
                "tenant_id": tid,
                "event_type": "sla_breach",
                "ticket_id": incident_id,
                "tracking_id": tracking_id,
            }
        )
        >= 1
    )

    # Second sweep is idempotent — already breached, no re-scan hit as running.
    second = jobs_service.sweep_sla_overdue(tenant_id=tid)
    assert second["breached"] == 0


def test_delivery_retry_job_and_lease_idempotency(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    class Flaky:
        channel = "email"
        calls = 0

        def deliver(self, *, recipient_address, subject, body, channel_config):
            self.calls += 1
            if self.calls == 1:
                return DeliveryResult(
                    status="failed",
                    provider="smtp_flaky",
                    recipient_address=recipient_address,
                    error="temporary",
                )
            return DeliveryResult(
                status="sent",
                provider="smtp_flaky",
                recipient_address=recipient_address,
            )

    flaky = Flaky()
    set_email_provider_for_tests(flaky)
    try:
        from app.db import get_database

        db = get_database()
        db["users"].insert_one(
            {
                "user_id": "user-retry",
                "username": "retry.user",
                "email": "retry@example.com",
                "is_platform_admin": False,
            }
        )
        db["memberships"].insert_one(
            {
                "membership_id": "mem-retry01",
                "user_id": "user-retry",
                "tenant_id": MIGRATION_TENANT_ID,
                "role": "member",
            }
        )
        channel_settings_service.upsert_channel_settings(
            tenant_id=MIGRATION_TENANT_ID,
            channel="email",
            payload={
                "enabled": True,
                "smtp_host": "smtp.test.local",
                "from_address": "itsm@example.com",
                "smtp_password_env_ref": "ITSM_SMTP_PASSWORD",
            },
            actor={"user_id": "admin", "username": "admin"},
        )
        attempt = delivery_service.deliver_one(
            tenant_id=MIGRATION_TENANT_ID,
            channel="email",
            recipient_user_id="retry.user",
            subject="Retry me",
            body="Body",
            event_type="assignment",
        )
        assert attempt["status"] == "failed"
        assert attempt["next_retry_at"] is not None

        # Make retry immediately due.
        get_itsm_database()["itsm_notification_deliveries"].update_one(
            {"delivery_id": attempt["delivery_id"]},
            {
                "$set": {
                    "next_retry_at": datetime.now(timezone.utc) - timedelta(seconds=1)
                }
            },
        )

        result = jobs_service.retry_notification_deliveries(
            tenant_id=MIGRATION_TENANT_ID
        )
        assert result["retried"] >= 1
        assert result["sent"] >= 1
        row = get_itsm_database()["itsm_notification_deliveries"].find_one(
            {"delivery_id": attempt["delivery_id"]}
        )
        assert row["status"] == "sent"
        assert row["attempt"] >= 2

        # Lease: first holder acquires; second distinct holder blocked.
        lease1 = jobs_service.try_acquire_lease(
            JOB_SLA_SWEEPER, lease_seconds=30, holder="worker-a"
        )
        assert lease1 is not None
        lease2 = jobs_service.try_acquire_lease(
            JOB_SLA_SWEEPER, lease_seconds=30, holder="worker-b"
        )
        assert lease2 is None
        # Same holder renews.
        lease1b = jobs_service.try_acquire_lease(
            JOB_SLA_SWEEPER, lease_seconds=30, holder="worker-a"
        )
        assert lease1b is not None
    finally:
        set_email_provider_for_tests(None)


def test_forced_tick_api_and_report_placeholder(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    status = client.get("/api/itsm/jobs/status", headers=auth_headers)
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["enabled"] is False
    assert JOB_SLA_SWEEPER in body["jobs"]
    assert JOB_DELIVERY_RETRIES in body["jobs"]
    assert JOB_REPORT_SCHEDULES in body["jobs"]
    assert "workflow_schedules" in body["jobs"]

    tick = client.post(
        "/api/itsm/jobs/tick",
        headers=auth_headers,
        json={
            "force": True,
            "scope_tenant": True,
            "jobs": [JOB_SLA_SWEEPER, JOB_REPORT_SCHEDULES],
        },
    )
    assert tick.status_code == 200, tick.text
    payload = tick.json()
    assert payload["ok"] is True
    # N3 wires report_schedules for real; empty due set is fine.
    assert payload["jobs"][JOB_REPORT_SCHEDULES].get("job") == JOB_REPORT_SCHEDULES
    assert payload["jobs"][JOB_SLA_SWEEPER]["tenant_filter"] == MIGRATION_TENANT_ID

    # On-read SLA path still works with runner disabled (prior behavior).
    created = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={
            "title": "On-read breach",
            "description": "x",
            "priority": "p1",
            "category": "network",
        },
    )
    assert created.status_code == 201
    incident_id = created.json()["incident_id"]
    tid = created.json()["tenant_id"]
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    get_itsm_database()["itsm_sla_tracking"].insert_one(
        {
            "tenant_id": tid,
            "tracking_id": "SLA-ONREAD01",
            "policy_id": "SLA-POL",
            "ticket_type": "incident",
            "ticket_id": incident_id,
            "metric": "response",
            "status": "running",
            "due_at": past,
            "started_at": past - timedelta(minutes=30),
            "created_at": past,
            "updated_at": past,
        }
    )
    listed = client.get(
        "/api/itsm/sla/tracking?overdue=true",
        headers=auth_headers,
    )
    assert listed.status_code == 200, listed.text
    # Listing refreshes breaches on read.
    doc = get_itsm_database()["itsm_sla_tracking"].find_one(
        {"tracking_id": "SLA-ONREAD01"}
    )
    assert doc["status"] == "breached"


def test_frontend_version_pin_for_n2() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.7"' in html
