"""ITSM N1 outbound notification delivery — email + SMS/Slack scaffold."""

from __future__ import annotations

from dataclasses import dataclass

from app import __version__
from app.db import get_database, get_itsm_database
from app.itsm.services import notification_channels as channel_settings_service
from app.itsm.services import notification_delivery as delivery_service
from app.itsm.services import notifications as notifications_service
from app.itsm.services.notification_providers import (
    DeliveryResult,
    set_email_provider_for_tests,
)
from app.permissions import (
    ALL_PERMISSIONS,
    PERM_ITSM_NOTIFICATION_ADMIN,
    permissions_for_role,
)
from app.tenancy import MEMBERSHIP_ROLE_ADMIN, MEMBERSHIP_ROLE_VIEWER, MIGRATION_TENANT_ID
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_notification_delivery_slice() -> None:
    assert __version__ == "0.73.0"


def test_notification_admin_permission_in_catalog() -> None:
    assert PERM_ITSM_NOTIFICATION_ADMIN in ALL_PERMISSIONS
    assert PERM_ITSM_NOTIFICATION_ADMIN in permissions_for_role(MEMBERSHIP_ROLE_ADMIN)
    assert PERM_ITSM_NOTIFICATION_ADMIN not in permissions_for_role(
        MEMBERSHIP_ROLE_VIEWER
    )


@dataclass
class _FakeEmail:
    channel: str = "email"
    calls: list | None = None

    def __post_init__(self) -> None:
        self.calls = []

    def deliver(self, *, recipient_address, subject, body, channel_config):
        self.calls.append(
            {
                "recipient_address": recipient_address,
                "subject": subject,
                "body": body,
                "channel_config": dict(channel_config),
            }
        )
        return DeliveryResult(
            status="sent",
            provider="smtp_fake",
            recipient_address=recipient_address,
        )


def _seed_user_with_email(
    *,
    user_id: str = "user-ops-alice",
    username: str = "ops.alice",
    email: str = "ops.alice@example.com",
    tenant_id: str = MIGRATION_TENANT_ID,
) -> None:
    db = get_database()
    db["users"].delete_many({"user_id": user_id})
    db["users"].insert_one(
        {
            "user_id": user_id,
            "username": username,
            "email": email,
            "display_name": "Ops Alice",
            "is_platform_admin": False,
        }
    )
    db["memberships"].delete_many({"user_id": user_id, "tenant_id": tenant_id})
    db["memberships"].insert_one(
        {
            "membership_id": f"mem-{user_id[-8:]}",
            "user_id": user_id,
            "tenant_id": tenant_id,
            "role": "member",
        }
    )


def _enable_email_channel(tenant_id: str) -> None:
    channel_settings_service.upsert_channel_settings(
        tenant_id=tenant_id,
        channel="email",
        payload={
            "enabled": True,
            "smtp_host": "smtp.test.local",
            "smtp_port": 587,
            "smtp_use_tls": True,
            "smtp_username": "itsm",
            "smtp_password_env_ref": "ITSM_SMTP_PASSWORD",
            "from_address": "itsm@example.com",
        },
        actor={"user_id": "admin", "username": "admin"},
    )


def _create_incident(client: TestClient, auth_headers: dict[str, str], **overrides):
    body = {
        "title": "VPN edge down",
        "description": "Users cannot connect",
        "priority": "p2",
        "category": "network",
    }
    body.update(overrides)
    resp = client.post("/api/itsm/incidents", headers=auth_headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_assign_incident_fans_out_email_attempt(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    fake = _FakeEmail()
    set_email_provider_for_tests(fake)
    try:
        _seed_user_with_email()
        incident = _create_incident(client, auth_headers)
        tid = incident["tenant_id"]
        _enable_email_channel(tid)
        itsm = get_itsm_database()

        assigned = client.patch(
            f"/api/itsm/incidents/{incident['incident_id']}",
            headers=auth_headers,
            json={"assignee_user_id": "ops.alice"},
        )
        assert assigned.status_code == 200, assigned.text

        assert (
            itsm["itsm_notifications"].count_documents(
                {
                    "event_type": "assignment",
                    "ticket_id": incident["incident_id"],
                    "recipient_user_id": "ops.alice",
                    "channel": "in_app",
                }
            )
            == 1
        )
        email_attempts = list(
            itsm["itsm_notification_deliveries"].find(
                {
                    "channel": "email",
                    "ticket_id": incident["incident_id"],
                    "recipient_user_id": "ops.alice",
                }
            )
        )
        assert len(email_attempts) == 1
        assert email_attempts[0]["status"] == "sent"
        assert email_attempts[0]["recipient_address"] == "ops.alice@example.com"
        assert email_attempts[0]["provider"] == "smtp_fake"
        assert len(fake.calls) == 1
        assert fake.calls[0]["recipient_address"] == "ops.alice@example.com"

        # Disabled / scaffold channels still record skipped attempts when enabled=False.
        sms = list(
            itsm["itsm_notification_deliveries"].find(
                {"channel": "sms", "ticket_id": incident["incident_id"]}
            )
        )
        assert len(sms) == 1
        assert sms[0]["status"] == "skipped"
        assert sms[0]["error"] == "channel_disabled"
    finally:
        set_email_provider_for_tests(None)


def test_non_configured_email_skipped_with_audit_row(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    # Use real SMTP provider so missing host produces skipped (not a fake send).
    set_email_provider_for_tests(None)
    _seed_user_with_email()
    incident = _create_incident(client, auth_headers)
    tid = incident["tenant_id"]
    # Enable channel but leave SMTP host blank → provider skips.
    channel_settings_service.upsert_channel_settings(
        tenant_id=tid,
        channel="email",
        payload={
            "enabled": True,
            "smtp_host": "",
            "from_address": "itsm@example.com",
        },
        actor={"user_id": "admin", "username": "admin"},
    )

    notifications_service.emit(
        tenant_id=tid,
        event_type="assignment",
        recipient_user_ids=["ops.alice"],
        subject="Assigned: INC",
        body="You were assigned",
        ticket_type="incident",
        ticket_id=incident["incident_id"],
        actor={"username": "manager", "user_id": "manager"},
    )
    itsm = get_itsm_database()
    row = itsm["itsm_notification_deliveries"].find_one(
        {"channel": "email", "recipient_user_id": "ops.alice"}
    )
    assert row is not None
    assert row["status"] == "skipped"
    assert row["error"] == "smtp_not_configured"


def test_cross_tenant_recipient_denied(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    fake = _FakeEmail()
    set_email_provider_for_tests(fake)
    try:
        db = get_database()
        db["users"].insert_one(
            {
                "user_id": "user-other",
                "username": "other.user",
                "email": "other@example.com",
                "is_platform_admin": False,
            }
        )
        db["memberships"].insert_one(
            {
                "membership_id": "mem-other01",
                "user_id": "user-other",
                "tenant_id": "tenant-other-org",
                "role": "member",
            }
        )
        incident = _create_incident(client, auth_headers)
        tid = incident["tenant_id"]
        _enable_email_channel(tid)

        attempt = delivery_service.deliver_one(
            tenant_id=tid,
            channel="email",
            recipient_user_id="other.user",
            subject="Nope",
            body="Cross tenant",
            event_type="assignment",
            ticket_type="incident",
            ticket_id=incident["incident_id"],
        )
        assert attempt["status"] == "denied"
        assert attempt["error"] == "cross_tenant_recipient_denied"
        assert fake.calls == []
    finally:
        set_email_provider_for_tests(None)


def test_channel_settings_api_and_deliveries_list(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    # HTTP Basic uses effective admin role on the migration tenant.
    listed = client.get("/api/itsm/notifications/channels", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["count"] == 3
    channels = {row["channel"] for row in payload["items"]}
    assert channels == {"email", "sms", "slack"}

    saved = client.put(
        "/api/itsm/notifications/channels/email",
        headers=auth_headers,
        json={
            "enabled": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "smtp_use_tls": False,
            "smtp_username": "relay",
            "smtp_password_env_ref": "ITSM_SMTP_PASSWORD",
            "from_address": "noreply@example.com",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["enabled"] is True
    assert saved.json()["smtp_host"] == "smtp.example.com"
    assert saved.json()["smtp_password_env_ref"] == "ITSM_SMTP_PASSWORD"

    bad_ref = client.put(
        "/api/itsm/notifications/channels/email",
        headers=auth_headers,
        json={"smtp_password_env_ref": "not-valid"},
    )
    assert bad_ref.status_code == 422

    deliveries = client.get(
        "/api/itsm/notifications/deliveries", headers=auth_headers
    )
    assert deliveries.status_code == 200, deliveries.text
    assert "items" in deliveries.json()


def test_emit_best_effort_survives_provider_failure(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    class Boom:
        channel = "email"

        def deliver(self, **kwargs):
            raise RuntimeError("smtp boom")

    set_email_provider_for_tests(Boom())  # type: ignore[arg-type]
    try:
        _seed_user_with_email()
        incident = _create_incident(client, auth_headers)
        tid = incident["tenant_id"]
        _enable_email_channel(tid)

        # Provider.deliver raising must not break emit — SmtpEmailProvider catches,
        # but inject a provider that raises to prove fan-out wrapper is safe.
        # Our SmtpEmailProvider catches; Boom raises → fan_out catches.
        rows = notifications_service.emit_best_effort(
            tenant_id=tid,
            event_type="assignment",
            recipient_user_ids=["ops.alice"],
            subject="Assigned",
            body="Body",
            ticket_type="incident",
            ticket_id=incident["incident_id"],
            actor={"username": "manager", "user_id": "manager"},
        )
        assert len(rows) == 1
        assert rows[0]["channel"] == "in_app"
    finally:
        set_email_provider_for_tests(None)


def test_frontend_delivery_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.73.0"' in html
    assert 'id="itsmNotifChannelsPanel"' in html
    assert 'id="itsmNotifEmailEnabled"' in html
    assert 'id="itsmNotifDeliveryBody"' in html
    assert "itsm/notifications.js?v=0.73.0" in html
