"""Provider-neutral OIDC helpers (Authorization Code + PKCE).

Compatible with Keycloak, Entra ID, and other standards-compliant IdPs.
Discovery uses ``{issuer}/.well-known/openid-configuration``.

Login state/PKCE are stored in the Starlette session **and** a short-lived
signed cookie so the Auth Code round-trip survives more reliably. Cookies are
host-scoped: ``localhost`` and ``127.0.0.1`` are different jars — callers must
use the same host as ``OIDC_REDIRECT_URI``.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from jwt import PyJWKClient

from .config import Settings

logger = logging.getLogger(__name__)

SESSION_OIDC_STATE = "oidc_state"
SESSION_OIDC_VERIFIER = "oidc_code_verifier"
SESSION_OIDC_NONCE = "oidc_nonce"
SESSION_AUTH = "auth"
SESSION_ID_TOKEN = "oidc_id_token"

OIDC_PENDING_COOKIE = "svrmon24_oidc_pending"
OIDC_PENDING_MAX_AGE = 600  # seconds
OIDC_PENDING_SALT = "svrmon24-oidc-pending-v1"

HOST_MISMATCH_HINT = (
    "Open the app using the same host as OIDC_REDIRECT_URI. "
    "`localhost` and `127.0.0.1` are different cookie jars — mixing them "
    "drops the OIDC state between /auth/login and /auth/callback."
)


class OidcError(Exception):
    """Raised when OIDC discovery, token exchange, or validation fails."""


def redirect_origin(settings: Settings) -> str:
    """Return ``scheme://host[:port]`` from ``OIDC_REDIRECT_URI``."""
    parsed = urlparse(settings.oidc_redirect_uri or "")
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return f"http://localhost:{settings.app_port}"


def redirect_hostname(settings: Settings) -> str:
    return (urlparse(settings.oidc_redirect_uri or "").hostname or "").lower()


def request_hostname(request_url_hostname: str | None) -> str:
    return (request_url_hostname or "").lower()


def hosts_match(settings: Settings, request_url_hostname: str | None) -> bool:
    expected = redirect_hostname(settings)
    actual = request_hostname(request_url_hostname)
    if not expected or not actual:
        return True
    return expected == actual


def host_mismatch_message(settings: Settings, request_url_hostname: str | None) -> str:
    expected = redirect_hostname(settings) or "(unset)"
    actual = request_hostname(request_url_hostname) or "(unknown)"
    return (
        f"Browser host `{actual}` does not match OIDC_REDIRECT_URI host `{expected}`. "
        f"{HOST_MISMATCH_HINT} Use {redirect_origin(settings)}/ consistently."
    )


def _pending_serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt=OIDC_PENDING_SALT)


def dump_oidc_pending(settings: Settings, payload: dict[str, str]) -> str:
    """Sign state/nonce/verifier for a short-lived pending cookie."""
    return _pending_serializer(settings).dumps(payload)


def load_oidc_pending(settings: Settings, token: str | None) -> dict[str, str] | None:
    if not token:
        return None
    try:
        data = _pending_serializer(settings).loads(token, max_age=OIDC_PENDING_MAX_AGE)
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {str(k): str(v) for k, v in data.items()}


def make_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for S256 PKCE."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def make_state_and_nonce() -> tuple[str, str]:
    return secrets.token_urlsafe(24), secrets.token_urlsafe(24)


@lru_cache(maxsize=8)
def _cached_discovery(issuer: str) -> dict[str, Any]:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    with httpx.Client(timeout=10.0) as client:
        response = client.get(url)
        response.raise_for_status()
        data = response.json()
    if not data.get("authorization_endpoint") or not data.get("token_endpoint"):
        raise OidcError("OIDC discovery missing authorization_endpoint or token_endpoint")
    return data


def clear_discovery_cache() -> None:
    """Clear cached discovery documents (tests / issuer rotation)."""
    _cached_discovery.cache_clear()


def fetch_discovery(settings: Settings) -> dict[str, Any]:
    if not settings.oidc_issuer:
        raise OidcError("OIDC_ISSUER is not configured")
    try:
        return _cached_discovery(settings.oidc_issuer.rstrip("/"))
    except httpx.HTTPError as exc:
        raise OidcError(f"OIDC discovery failed: {exc}") from exc


def build_authorization_url(
    settings: Settings,
    *,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    discovery = fetch_discovery(settings)
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": settings.oidc_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return discovery["authorization_endpoint"] + "?" + urlencode(params)


def exchange_code_for_tokens(settings: Settings, *, code: str, code_verifier: str) -> dict[str, Any]:
    discovery = fetch_discovery(settings)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oidc_redirect_uri,
        "client_id": settings.oidc_client_id,
        "code_verifier": code_verifier,
    }
    # Confidential clients (Entra / many Keycloak setups) also send the secret.
    auth = None
    if settings.oidc_client_secret:
        auth = (settings.oidc_client_id, settings.oidc_client_secret)
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(discovery["token_endpoint"], data=data, auth=auth)
            if response.status_code >= 400:
                raise OidcError(
                    f"Token endpoint error {response.status_code}: {response.text[:300]}"
                )
            return response.json()
    except httpx.HTTPError as exc:
        raise OidcError(f"Token exchange failed: {exc}") from exc


def validate_id_token(
    settings: Settings,
    id_token: str,
    *,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Validate an ID token via the IdP JWKS and return claims."""
    discovery = fetch_discovery(settings)
    jwks_uri = discovery.get("jwks_uri")
    if not jwks_uri:
        raise OidcError("OIDC discovery missing jwks_uri")

    issuer = settings.oidc_issuer.rstrip("/")
    # Some IdPs append a trailing slash inconsistently; accept both.
    audience = settings.oidc_client_id
    try:
        jwks_client = PyJWKClient(jwks_uri, cache_keys=True)
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            audience=audience,
            issuer=[issuer, issuer + "/"],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise OidcError(f"ID token validation failed: {exc}") from exc

    if nonce is not None and claims.get("nonce") != nonce:
        raise OidcError("ID token nonce mismatch")

    # Soft clock skew check already covered by PyJWT; log age for ops.
    iat = claims.get("iat")
    if isinstance(iat, (int, float)) and iat > time.time() + 120:
        raise OidcError("ID token issued in the future")

    return claims


def claims_to_session_auth(claims: dict[str, Any]) -> dict[str, Any]:
    """Map OIDC claims to the server session ``auth`` payload."""
    username = (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("name")
        or claims.get("sub")
    )
    if not username:
        raise OidcError("ID token missing usable username claim")
    return {
        "username": str(username),
        "subject": str(claims.get("sub") or ""),
        "email": claims.get("email"),
        "auth_method": "oidc",
        "name": claims.get("name"),
    }


def end_session_url(
    settings: Settings,
    *,
    id_token: str | None,
    post_logout_redirect_uri: str,
) -> str | None:
    """Return IdP logout URL when ``end_session_endpoint`` is advertised."""
    try:
        discovery = fetch_discovery(settings)
    except OidcError:
        return None
    endpoint = discovery.get("end_session_endpoint")
    if not endpoint:
        return None
    params: dict[str, str] = {"post_logout_redirect_uri": post_logout_redirect_uri}
    if id_token:
        params["id_token_hint"] = id_token
    if settings.oidc_client_id:
        params["client_id"] = settings.oidc_client_id
    return endpoint + "?" + urlencode(params)
