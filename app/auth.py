"""Authentication for SVRMON24 — OIDC session (primary) + feature-flagged HTTP Basic.

Basic auth is a migration/testing coexistence path only. It must never bypass
future tenant-scoped authorization once multi-tenant isolation lands. Defaults
are production-oriented: ``BASIC_AUTH_ENABLED=false``.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import Settings, get_settings
from .oidc import SESSION_AUTH

security = HTTPBasic(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    """Authenticated principal for the current request."""

    username: str
    auth_method: str  # "oidc" | "basic"
    subject: str | None = None
    email: str | None = None
    name: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "auth_method": self.auth_method,
            "subject": self.subject,
            "email": self.email,
            "name": self.name,
        }


def _www_authenticate(settings: Settings) -> str:
    if settings.basic_auth_enabled:
        return "Basic"
    return 'Bearer realm="svrmon24"'


def _unauthorized(settings: Settings, detail: str = "Authentication required") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": _www_authenticate(settings)},
    )


def _user_from_session(request: Request) -> AuthUser | None:
    raw = request.session.get(SESSION_AUTH)
    if not isinstance(raw, dict):
        return None
    username = raw.get("username")
    method = raw.get("auth_method")
    if not username or method != "oidc":
        return None
    return AuthUser(
        username=str(username),
        auth_method="oidc",
        subject=raw.get("subject"),
        email=raw.get("email"),
        name=raw.get("name"),
    )


def verify_basic_credentials(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(security)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    """Validate HTTP Basic credentials when the Basic feature flag is on.

    Kept for direct use / legacy callers. Prefer :func:`require_user` on routes.
    """
    if not settings.basic_auth_enabled:
        raise _unauthorized(settings, "HTTP Basic authentication is disabled")

    if credentials is None:
        raise _unauthorized(settings)

    username_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        settings.basic_auth_username.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        settings.basic_auth_password.encode("utf-8"),
    )
    if not (username_ok and password_ok):
        raise _unauthorized(settings, "Invalid credentials")
    return credentials.username


def require_user(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(security)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthUser:
    """Accept an OIDC server session, or HTTP Basic when the feature flag is on.

    Order: OIDC session first (when OIDC is enabled), then Basic if
    ``BASIC_AUTH_ENABLED``. Basic must not be treated as a tenant-auth bypass
    in later phases — it remains a shared migration credential only.
    """
    if settings.oidc_enabled:
        session_user = _user_from_session(request)
        if session_user is not None:
            return session_user

    if settings.basic_auth_enabled:
        if credentials is None:
            raise _unauthorized(settings)
        username_ok = secrets.compare_digest(
            credentials.username.encode("utf-8"),
            settings.basic_auth_username.encode("utf-8"),
        )
        password_ok = secrets.compare_digest(
            credentials.password.encode("utf-8"),
            settings.basic_auth_password.encode("utf-8"),
        )
        if not (username_ok and password_ok):
            raise _unauthorized(settings, "Invalid credentials")
        return AuthUser(username=credentials.username, auth_method="basic")

    if not settings.oidc_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No authentication method enabled. Configure OIDC "
                "(OIDC_ENABLED=true) or temporarily enable BASIC_AUTH_ENABLED "
                "for migration/testing."
            ),
        )

    raise _unauthorized(settings)


# Backwards-compatible alias used while routers migrate.
verify_credentials = require_user
