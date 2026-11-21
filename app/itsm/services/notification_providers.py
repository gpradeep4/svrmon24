"""Outbound notification providers — email (SMTP) + SMS/Slack scaffolds.

Secrets are resolved from environment variable *names* stored in tenant
channel settings (never secret values in Mongo). Delivery is best-effort.
"""

from __future__ import annotations

import logging
import os
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_ENV_REF_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class ProviderError(Exception):
    def __init__(self, message: str, *, status: str = "failed") -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class DeliveryResult:
    status: str  # sent | failed | skipped | denied
    provider: str
    recipient_address: str | None = None
    error: str | None = None
    detail: dict[str, Any] | None = None


class NotificationProvider(Protocol):
    channel: str

    def deliver(
        self,
        *,
        recipient_address: str,
        subject: str,
        body: str,
        channel_config: dict[str, Any],
    ) -> DeliveryResult: ...


def normalize_env_ref(value: str | None) -> str | None:
    if not value:
        return None
    ref = value.strip()
    if not ref:
        return None
    if not _ENV_REF_RE.match(ref):
        raise ProviderError(
            f"env_ref must match {_ENV_REF_RE.pattern}",
            status="failed",
        )
    return ref


def resolve_env_secret(env_ref: str | None) -> str:
    if not env_ref:
        return ""
    return os.getenv(env_ref, "").strip()


class SmtpEmailProvider:
    """Deliver email via SMTP. Uses stdlib smtplib; injectable for tests."""

    channel = "email"

    def __init__(
        self,
        *,
        send_fn: Any | None = None,
    ) -> None:
        self._send_fn = send_fn or self._smtp_send

    def deliver(
        self,
        *,
        recipient_address: str,
        subject: str,
        body: str,
        channel_config: dict[str, Any],
    ) -> DeliveryResult:
        to_addr = (recipient_address or "").strip()
        if not to_addr or "@" not in to_addr:
            return DeliveryResult(
                status="skipped",
                provider="smtp",
                recipient_address=to_addr or None,
                error="missing_or_invalid_email",
            )

        host = str(channel_config.get("smtp_host") or "").strip()
        if not host:
            return DeliveryResult(
                status="skipped",
                provider="smtp",
                recipient_address=to_addr,
                error="smtp_not_configured",
            )

        from_addr = str(channel_config.get("from_address") or "").strip()
        if not from_addr or "@" not in from_addr:
            return DeliveryResult(
                status="skipped",
                provider="smtp",
                recipient_address=to_addr,
                error="from_address_not_configured",
            )

        port = int(channel_config.get("smtp_port") or 587)
        use_tls = bool(channel_config.get("smtp_use_tls", True))
        username = str(channel_config.get("smtp_username") or "").strip() or None
        password = resolve_env_secret(channel_config.get("smtp_password_env_ref"))

        msg = EmailMessage()
        msg["Subject"] = subject[:500]
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg.set_content(body[:4000] or subject)

        try:
            self._send_fn(
                host=host,
                port=port,
                use_tls=use_tls,
                username=username,
                password=password or None,
                message=msg,
            )
        except Exception as exc:  # noqa: BLE001 — provider never raises to callers
            logger.warning("smtp email delivery failed to=%s err=%s", to_addr, exc)
            return DeliveryResult(
                status="failed",
                provider="smtp",
                recipient_address=to_addr,
                error=str(exc)[:500],
            )
        return DeliveryResult(
            status="sent",
            provider="smtp",
            recipient_address=to_addr,
        )

    @staticmethod
    def _smtp_send(
        *,
        host: str,
        port: int,
        use_tls: bool,
        username: str | None,
        password: str | None,
        message: EmailMessage,
    ) -> None:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            if use_tls:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)


class SmsProviderScaffold:
    """Twilio-shaped SMS scaffold — records skipped until credentials configured."""

    channel = "sms"

    def deliver(
        self,
        *,
        recipient_address: str,
        subject: str,
        body: str,
        channel_config: dict[str, Any],
    ) -> DeliveryResult:
        to_addr = (recipient_address or "").strip()
        account_ref = channel_config.get("twilio_account_sid_env_ref")
        token_ref = channel_config.get("twilio_auth_token_env_ref")
        from_number = str(channel_config.get("twilio_from_number") or "").strip()
        account = resolve_env_secret(account_ref)
        token = resolve_env_secret(token_ref)
        if not (account and token and from_number and to_addr):
            return DeliveryResult(
                status="skipped",
                provider="twilio_scaffold",
                recipient_address=to_addr or None,
                error="sms_not_configured",
                detail={"scaffold": True},
            )
        # Scaffold only — do not call Twilio in this slice.
        logger.info(
            "sms scaffold would send to=%s from=%s subject=%s",
            to_addr,
            from_number,
            (subject or "")[:80],
        )
        return DeliveryResult(
            status="skipped",
            provider="twilio_scaffold",
            recipient_address=to_addr,
            error="sms_provider_scaffold_only",
            detail={"scaffold": True, "body_len": len(body or "")},
        )


class SlackProviderScaffold:
    """Slack webhook/token scaffold — skipped until env ref is set."""

    channel = "slack"

    def deliver(
        self,
        *,
        recipient_address: str,
        subject: str,
        body: str,
        channel_config: dict[str, Any],
    ) -> DeliveryResult:
        target = (recipient_address or "").strip() or str(
            channel_config.get("default_channel") or ""
        ).strip()
        webhook_ref = channel_config.get("webhook_url_env_ref")
        token_ref = channel_config.get("bot_token_env_ref")
        webhook = resolve_env_secret(webhook_ref)
        token = resolve_env_secret(token_ref)
        if not (webhook or token):
            return DeliveryResult(
                status="skipped",
                provider="slack_scaffold",
                recipient_address=target or None,
                error="slack_not_configured",
                detail={"scaffold": True},
            )
        logger.info(
            "slack scaffold would post target=%s subject=%s",
            target or "(default)",
            (subject or "")[:80],
        )
        return DeliveryResult(
            status="skipped",
            provider="slack_scaffold",
            recipient_address=target or None,
            error="slack_provider_scaffold_only",
            detail={"scaffold": True, "body_len": len(body or "")},
        )


_PROVIDERS: dict[str, NotificationProvider] = {
    "email": SmtpEmailProvider(),
    "sms": SmsProviderScaffold(),
    "slack": SlackProviderScaffold(),
}


def get_provider(channel: str) -> NotificationProvider | None:
    return _PROVIDERS.get(channel)


def set_email_provider_for_tests(provider: NotificationProvider | None) -> None:
    """Test hook to inject a fake SMTP provider."""
    if provider is None:
        _PROVIDERS["email"] = SmtpEmailProvider()
    else:
        _PROVIDERS["email"] = provider
