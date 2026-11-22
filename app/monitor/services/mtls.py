"""Agent mTLS acceptance sketch (L4) — feature-flagged, parallel to token auth.

Production intent (document / ops):
  1. Platform CA (OpenSSL or step-ca) issues short-lived client certs.
  2. Subject OU = ``agent_id``; SAN URI or DNS encodes ``tenant_id``.
  3. Reverse proxy (nginx / Envoy) terminates TLS with ``ssl_verify_client on``
     and forwards identity headers (never trust client-supplied cert PEMs
     without a verified proxy hop).
  4. API accepts either bearer agent token **or** verified mTLS identity on
     the same agent routes (heartbeat / future ingest).

This module implements the **header-acceptance stub** only — full CA
automation and cert issuance remain Ln. When
``MONITOR_AGENT_MTLS_ENABLED`` is false (default), mTLS paths are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ...config import Settings, get_settings

# Common reverse-proxy headers after successful client-cert verify.
HEADER_VERIFY = "x-ssl-client-verify"
HEADER_DN = "x-ssl-client-s-dn"
HEADER_FINGERPRINT = "x-ssl-client-fingerprint"
# Explicit OU / tenant hints (optional, when DN parsing is inconvenient).
HEADER_OU = "x-ssl-client-ou"
HEADER_TENANT = "x-ssl-client-tenant"


@dataclass(frozen=True)
class MtlsIdentity:
    """Verified (or sketch-verified) client-cert identity."""

    agent_id: str
    tenant_id: str | None
    fingerprint: str | None
    subject_dn: str | None
    verified: bool


_OU_RE = re.compile(r"(?:^|,)\s*OU\s*=\s*([^,/]+)", re.IGNORECASE)
_TENANT_URI_RE = re.compile(
    r"URI:svrmon24:tenant/([A-Za-z0-9._\-]+)", re.IGNORECASE
)


def mtls_enabled(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return bool(getattr(cfg, "monitor_agent_mtls_enabled", False))


def parse_subject_ou(subject_dn: str | None) -> str | None:
    text = (subject_dn or "").strip()
    if not text:
        return None
    match = _OU_RE.search(text)
    if not match:
        return None
    return match.group(1).strip() or None


def parse_tenant_from_san_hint(raw: str | None) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    match = _TENANT_URI_RE.search(text)
    if match:
        return match.group(1).strip() or None
    # Allow bare tenant id when forwarded via dedicated header.
    if text.startswith("tenant-") or text.startswith("tenant_"):
        return text
    return None


def extract_mtls_identity(
    headers: dict[str, str] | Any,
    *,
    settings: Settings | None = None,
) -> MtlsIdentity | None:
    """Extract agent identity from proxy-forwarded client-cert headers.

    Returns ``None`` when mTLS is disabled or headers are absent / unverified.
    Does **not** perform cryptographic verification itself — that is the
    reverse proxy's job when ``MONITOR_AGENT_MTLS_ENABLED`` is on.
    """
    if not mtls_enabled(settings):
        return None

    def _h(name: str) -> str:
        if hasattr(headers, "get"):
            # Starlette Headers are case-insensitive; dict may not be.
            val = headers.get(name) or headers.get(name.lower()) or headers.get(
                name.title()
            )
            return str(val or "").strip()
        return ""

    verify = _h(HEADER_VERIFY).lower()
    # Accept SUCCESS / SUCCESS:* / 0 (OpenSSL verify OK) style values.
    verified = verify in {"success", "ok", "0"} or verify.startswith("success")
    if not verified and verify:
        return None
    if not verify:
        # No verify header — refuse (fail-closed even when flag on).
        return None

    subject = _h(HEADER_DN) or None
    ou = _h(HEADER_OU) or parse_subject_ou(subject)
    if not ou:
        return None
    tenant = _h(HEADER_TENANT) or parse_tenant_from_san_hint(_h("x-ssl-client-san"))
    fingerprint = _h(HEADER_FINGERPRINT) or None
    return MtlsIdentity(
        agent_id=ou,
        tenant_id=tenant,
        fingerprint=fingerprint,
        subject_dn=subject,
        verified=True,
    )


def mtls_sketch_meta(settings: Settings | None = None) -> dict[str, Any]:
    """Surface for ``GET /api/monitor/meta`` / Agents admin empty-state."""
    cfg = settings or get_settings()
    enabled = mtls_enabled(cfg)
    return {
        "enabled": enabled,
        "mode": "proxy_header_stub" if enabled else "disabled",
        "notes": (
            "Optional client cert: platform CA issues agent cert; API accepts "
            "cert OU=agent_id + tenant SAN when MONITOR_AGENT_MTLS_ENABLED=true "
            "and the reverse proxy sets X-SSL-Client-Verify=SUCCESS plus DN. "
            "Token path remains primary; mTLS is a parallel accept on agent routes. "
            "Full CA automation is Ln."
        ),
        "headers": [
            HEADER_VERIFY,
            HEADER_DN,
            HEADER_OU,
            HEADER_TENANT,
            HEADER_FINGERPRINT,
        ],
        "openssl_example": (
            "openssl req -new -key agent.key -subj "
            "'/CN=svrmon-agent/OU=agt-EXAMPLE/O=svrmon24' "
            "-addext 'subjectAltName=URI:svrmon24:tenant/tenant-example'"
        ),
    }
