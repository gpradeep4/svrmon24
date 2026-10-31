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
    HOST_MISMATCH_HINT,
    OIDC_PENDING_COOKIE,
    OIDC_PENDING_MAX_AGE,
    SESSION_AUTH,
    SESSION_ID_TOKEN,
    SESSION_OIDC_NONCE,
    SESSION_OIDC_STATE,
    SESSION_OIDC_VERIFIER,
    OidcError,
    build_authorization_url,
    claims_to_session_auth,
    dump_oidc_pending,
    end_session_url,
    exchange_code_for_tokens,
    host_mismatch_message,
    hosts_match,
    load_oidc_pending,
    make_pkce_pair,
    make_state_and_nonce,
    redirect_origin,
    validate_id_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

AUTH_ERROR_STATE = "oidc_state"
AUTH_ERROR_PROVIDER = "oidc_provider"
AUTH_ERROR_CONFIG = "oidc_config"


def _home_url(settings: Settings, *, auth_error: str | None = None) -> str:
    base = redirect_origin(settings) + "/"
    if auth_error:
        return f"{base}?auth_error={auth_error}"
    return base


def _post_logout_redirect(settings: Settings) -> str:
    return _home_url(settings)


def _set_pending_cookie(
    response: RedirectResponse, settings: Settings, token: str
) -> None:
    response.set_cookie(
        key=OIDC_PENDING_COOKIE,
        value=token,
        max_age=OIDC_PENDING_MAX_AGE,
        httponly=True,
        samesite=(settings.session_same_site or "lax").lower(),
        secure=bool(settings.session_https_only),
        path="/",
    )


def _clear_pending_cookie(response: RedirectResponse, settings: Settings) -> None:
    response.delete_cookie(
        key=OIDC_PENDING_COOKIE,
        path="/",
        httponly=True,
        samesite=(settings.session_same_site or "lax").lower(),
        secure=bool(settings.session_https_only),
    )


def _read_pending(
    request: Request, settings: Settings
) -> tuple[str | None, str | None, str | None]:
    """Return ``(state, nonce, verifier)`` from session and/or pending cookie."""
    expected_state = request.session.pop(SESSION_OIDC_STATE, None)
    nonce = request.session.pop(SESSION_OIDC_NONCE, None)
    verifier = request.session.pop(SESSION_OIDC_VERIFIER, None)

    cookie_payload = load_oidc_pending(
        settings, request.cookies.get(OIDC_PENDING_COOKIE)
    )
    if cookie_payload:
        expected_state = expected_state or cookie_payload.get("state")
        nonce = nonce or cookie_payload.get("nonce")
        verifier = verifier or cookie_payload.get("verifier")

    return expected_state, nonce, verifier


@router.get("/api/auth/config")
def auth_config(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Public auth feature flags for the vanilla UI (no secrets)."""
    origin = redirect_origin(settings)
    match = hosts_match(settings, request.url.hostname)
    return {
        "basic_auth_enabled": settings.basic_auth_enabled,
        "oidc_enabled": settings.oidc_enabled,
        "login_path": "/auth/login",
        "logout_path": "/auth/logout",
        "callback_path": "/auth/callback",
        "redirect_uri": settings.oidc_redirect_uri,
        "expected_origin": origin,
        "request_host": request.url.hostname,
        "host_matches_redirect": match,
        "host_hint": HOST_MISMATCH_HINT,
        # Hint only — never auto-admin first public registrant (later phase).
        "notes": (
            "OIDC is provider-neutral (Entra ID / Keycloak). "
            "HTTP Basic is migration-only and disabled by default. "
            "Use one browser host consistently (localhost OR 127.0.0.1)."
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

    # Cookies are host-scoped. If the user opened 127.0.0.1 while redirect_uri
    # is localhost (or reverse), bounce to the redirect URI host first.
    if not hosts_match(settings, request.url.hostname):
        target = redirect_origin(settings) + "/auth/login"
        logger.info(
            "oidc_login_host_redirect from=%s to=%s",
            request.url.hostname,
            urlparse(target).hostname,
        )
        return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)

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

    response = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    pending = dump_oidc_pending(
        settings,
        {"state": state, "nonce": nonce, "verifier": verifier},
    )
    _set_pending_cookie(response, settings, pending)
    # Ensure session cookie is written with this response.
    request.session["oidc_login_started"] = True
    return response


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

    def fail(auth_error: str, log_detail: str) -> RedirectResponse:
        logger.warning("oidc_callback_failed detail=%s", log_detail)
        response = RedirectResponse(
            url=_home_url(settings, auth_error=auth_error),
            status_code=status.HTTP_302_FOUND,
        )
        _clear_pending_cookie(response, settings)
        return response

    if error:
        detail = error_description or error
        return fail(AUTH_ERROR_PROVIDER, f"provider error: {detail}")

    if not code or not state:
        return fail(AUTH_ERROR_STATE, "missing code or state")

    if not hosts_match(settings, request.url.hostname):
        return fail(
            AUTH_ERROR_STATE,
            host_mismatch_message(settings, request.url.hostname),
        )

    expected_state, nonce, verifier = _read_pending(request, settings)
    if not expected_state or state != expected_state or not verifier:
        detail = (
            "Invalid or expired OIDC state. "
            + host_mismatch_message(settings, request.url.hostname)
            if not expected_state
            else "Invalid or expired OIDC state (state mismatch)."
        )
        return fail(AUTH_ERROR_STATE, detail)

    try:
        tokens = exchange_code_for_tokens(settings, code=code, code_verifier=verifier)
        id_token = tokens.get("id_token")
        if not id_token:
            raise OidcError("Token response missing id_token")
        claims = validate_id_token(settings, id_token, nonce=nonce)
        auth_payload = claims_to_session_auth(claims)
    except OidcError as exc:
        return fail(AUTH_ERROR_PROVIDER, str(exc))

    request.session.pop("oidc_login_started", None)
    request.session[SESSION_AUTH] = auth_payload
    request.session[SESSION_ID_TOKEN] = id_token
    logger.info(
        "oidc_login_success username=%s subject=%s",
        auth_payload.get("username"),
        auth_payload.get("subject"),
    )
    response = RedirectResponse(url=_home_url(settings), status_code=status.HTTP_302_FOUND)
    _clear_pending_cookie(response, settings)
    return response


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
            response = RedirectResponse(url=idp_logout, status_code=status.HTTP_302_FOUND)
            _clear_pending_cookie(response, settings)
            return response

    response = RedirectResponse(url=redirect_home, status_code=status.HTTP_302_FOUND)
    _clear_pending_cookie(response, settings)
    return response


@router.get("/api/me")
def whoami(user: AuthUser = Depends(require_user)) -> dict[str, Any]:
    """Return the authenticated principal (OIDC session or Basic)."""
    return user.as_dict()
