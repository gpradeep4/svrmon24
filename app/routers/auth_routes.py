"""OIDC login / callback / logout and public auth configuration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from ..auth import AuthUser, require_user
from ..config import Settings, get_settings
from ..oidc import (
    SESSION_AUTH,
    SESSION_ID_TOKEN,
    SESSION_OIDC_NONCE,
    SESSION_OIDC_STATE,
    SESSION_OIDC_VERIFIER,
    OidcError,
    build_authorization_url,
    claims_to_session_auth,
    end_session_url,
    exchange_code_for_tokens,
    make_pkce_pair,
    make_state_and_nonce,
    validate_id_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


def _post_logout_redirect(settings: Settings) -> str:
    """Derive the app origin from the configured OIDC redirect URI."""
    parsed = urlparse(settings.oidc_redirect_uri or f"http://localhost:{settings.app_port}/")
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    return (origin or f"http://localhost:{settings.app_port}") + "/"


@router.get("/api/auth/config")
def auth_config(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Public auth feature flags for the vanilla UI (no secrets)."""
    return {
        "basic_auth_enabled": settings.basic_auth_enabled,
        "oidc_enabled": settings.oidc_enabled,
        "login_path": "/auth/login",
        "logout_path": "/auth/logout",
        "callback_path": "/auth/callback",
        # Hint only — never auto-admin first public registrant (later phase).
        "notes": (
            "OIDC is provider-neutral (Entra ID / Keycloak). "
            "HTTP Basic is migration-only and disabled by default."
        ),
    }


@router.get("/auth/login")
def oidc_login(request: Request, settings: Settings = Depends(get_settings)) -> RedirectResponse:
    """Start Authorization Code + PKCE against the configured IdP."""
    if not settings.oidc_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC is disabled (set OIDC_ENABLED=true)",
        )
    if not settings.oidc_issuer or not settings.oidc_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC_ISSUER and OIDC_CLIENT_ID are required",
        )

    state, nonce = make_state_and_nonce()
    verifier, challenge = make_pkce_pair()
    request.session[SESSION_OIDC_STATE] = state
    request.session[SESSION_OIDC_NONCE] = nonce
    request.session[SESSION_OIDC_VERIFIER] = verifier

    try:
        url = build_authorization_url(
            settings, state=state, nonce=nonce, code_challenge=challenge
        )
    except OidcError as exc:
        logger.warning("oidc_login_failed detail=%s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/auth/callback")
def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Complete OIDC login: exchange code, validate ID token, set session."""
    if not settings.oidc_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC is disabled",
        )
    if error:
        detail = error_description or error
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OIDC provider error: {detail}",
        )
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state",
        )

    expected_state = request.session.pop(SESSION_OIDC_STATE, None)
    nonce = request.session.pop(SESSION_OIDC_NONCE, None)
    verifier = request.session.pop(SESSION_OIDC_VERIFIER, None)
    if not expected_state or state != expected_state or not verifier:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OIDC state",
        )

    try:
        tokens = exchange_code_for_tokens(settings, code=code, code_verifier=verifier)
        id_token = tokens.get("id_token")
        if not id_token:
            raise OidcError("Token response missing id_token")
        claims = validate_id_token(settings, id_token, nonce=nonce)
        auth_payload = claims_to_session_auth(claims)
    except OidcError as exc:
        logger.warning("oidc_callback_failed detail=%s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    request.session[SESSION_AUTH] = auth_payload
    request.session[SESSION_ID_TOKEN] = id_token
    logger.info(
        "oidc_login_success username=%s subject=%s",
        auth_payload.get("username"),
        auth_payload.get("subject"),
    )
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@router.get("/auth/logout")
@router.post("/auth/logout")
def oidc_logout(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Clear the local session; optionally redirect to the IdP end-session endpoint."""
    id_token = request.session.get(SESSION_ID_TOKEN)
    request.session.clear()

    redirect_home = _post_logout_redirect(settings)
    if settings.oidc_enabled and id_token:
        idp_logout = end_session_url(
            settings,
            id_token=str(id_token),
            post_logout_redirect_uri=redirect_home,
        )
        if idp_logout:
            return RedirectResponse(url=idp_logout, status_code=status.HTTP_302_FOUND)

    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)


@router.get("/api/me")
def whoami(user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    """Return the authenticated principal (OIDC session or Basic)."""
    return user.as_dict()
