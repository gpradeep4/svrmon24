"""OIDC login / callback / logout and public auth configuration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from ..auth import AuthUser, require_user
from ..config import Settings, get_settings
from ..db import DatabaseUnavailableError, ping_database
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


def _link_oidc_user(settings: Settings, auth_payload: dict[str, Any]) -> dict[str, Any] | None:
    """Create/link local user + migration-tenant member membership on OIDC login.

    Never grants platform admin. MongoDB outages are logged and skipped so login
    still succeeds (identity link retries on a later request /me enrichment).
    """
    from ..services import memberships as memberships_service
    from ..services import tenants as tenants_service
    from ..services import users as users_service
    from ..tenancy import MEMBERSHIP_ROLE_MEMBER, MIGRATION_TENANT_ID

    subject = auth_payload.get("subject")
    username = auth_payload.get("username")
    if not subject or not username or not settings.oidc_issuer:
        return None
    db_status = ping_database(settings)
    if not db_status.get("ok"):
        logger.warning("oidc_user_link_skipped mongodb unavailable")
        return None
    try:
        tenants_service.ensure_migration_tenant()
        user = users_service.ensure_user_from_oidc(
            issuer=settings.oidc_issuer,
            subject=str(subject),
            username=str(username),
            email=auth_payload.get("email"),
            display_name=auth_payload.get("name"),
        )
        # First (and subsequent) public logins get member only — never admin/platform-admin.
        memberships_service.ensure_membership(
            user_id=user["user_id"],
            tenant_id=MIGRATION_TENANT_ID,
            role=MEMBERSHIP_ROLE_MEMBER,
            upgrade_role=False,
        )
        if user.get("is_platform_admin"):
            logger.info(
                "oidc_login_platform_admin_preserved user_id=%s (CLI bootstrap only)",
                user.get("user_id"),
            )
        else:
            logger.info(
                "oidc_user_linked user_id=%s platform_admin=%s",
                user.get("user_id"),
                False,
            )
        return user
    except DatabaseUnavailableError as exc:
        logger.warning("oidc_user_link_skipped detail=%s", exc)
        return None
    except Exception:  # noqa: BLE001
        logger.exception("oidc_user_link_failed")
        return None


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

    linked = _link_oidc_user(settings, auth_payload)
    if linked is not None:
        auth_payload["user_id"] = linked.get("user_id")
        auth_payload["is_platform_admin"] = bool(linked.get("is_platform_admin"))

    request.session.pop("oidc_login_started", None)
    request.session[SESSION_AUTH] = auth_payload
    request.session[SESSION_ID_TOKEN] = id_token
    logger.info(
        "oidc_login_success username=%s subject=%s user_id=%s platform_admin=%s",
        auth_payload.get("username"),
        auth_payload.get("subject"),
        auth_payload.get("user_id"),
        auth_payload.get("is_platform_admin", False),
    )
    # signed_in=1 tells the SPA to resume /api/me before painting the app shell.
    home = _home_url(settings)
    target = home if home.endswith("/") else home + "/"
    target = f"{target}{'&' if '?' in target else '?'}signed_in=1"
    response = RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)
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
def whoami(
    request: Request,
    user: AuthUser = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Return the authenticated principal (OIDC session or Basic).

    When MongoDB is available and the principal is OIDC-linked, includes local
    ``user_id``, ``is_platform_admin`` (CLI-only), and migration tenant summary.
    """
    from ..services import memberships as memberships_service
    from ..services import tenants as tenants_service
    from ..services import users as users_service
    from ..tenancy import MIGRATION_TENANT_DISPLAY_NAME, MIGRATION_TENANT_ID

    payload = user.as_dict()
    payload["isolation_enforced"] = False
    payload["org_switcher_enabled"] = False
    payload["current_tenant_id"] = MIGRATION_TENANT_ID
    payload["current_tenant_display_name"] = MIGRATION_TENANT_DISPLAY_NAME
    payload["is_platform_admin"] = False
    payload["user_id"] = None
    payload["memberships"] = []

    # Prefer values already stored on the session after OIDC callback.
    session_auth = request.session.get(SESSION_AUTH)
    if isinstance(session_auth, dict):
        if session_auth.get("user_id"):
            payload["user_id"] = session_auth.get("user_id")
        if session_auth.get("is_platform_admin"):
            payload["is_platform_admin"] = bool(session_auth.get("is_platform_admin"))

    if user.auth_method != "oidc":
        payload["notes"] = (
            "HTTP Basic migration session — no local user/membership link. "
            "Basic must not bypass future tenant authorization."
        )
        return payload

    db_status = ping_database(settings)
    if not db_status.get("ok"):
        return payload

    try:
        local = None
        if user.subject and settings.oidc_issuer:
            local = users_service.get_user_by_oidc(settings.oidc_issuer, user.subject)
        if local is None and user.subject and settings.oidc_issuer:
            # Lazy link if callback could not reach Mongo at login time.
            local = _link_oidc_user(
                settings,
                {
                    "subject": user.subject,
                    "username": user.username,
                    "email": user.email,
                    "name": user.name,
                },
            )
        if local is None:
            return payload
        payload["user_id"] = local.get("user_id")
        payload["is_platform_admin"] = bool(local.get("is_platform_admin"))
        memberships = memberships_service.list_memberships_for_user(local["user_id"])
        payload["memberships"] = memberships
        tenant = tenants_service.get_current_tenant()
        payload["current_tenant_id"] = tenant.get("tenant_id", MIGRATION_TENANT_ID)
        payload["current_tenant_display_name"] = tenant.get(
            "display_name", MIGRATION_TENANT_DISPLAY_NAME
        )
        # Refresh session cache for subsequent requests.
        if isinstance(session_auth, dict):
            session_auth["user_id"] = local.get("user_id")
            session_auth["is_platform_admin"] = bool(local.get("is_platform_admin"))
            request.session[SESSION_AUTH] = session_auth
    except DatabaseUnavailableError:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("api_me_tenancy_enrichment_failed")
    return payload
