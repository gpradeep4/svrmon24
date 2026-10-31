"""Provider-neutral OIDC helpers (Authorization Code + PKCE).

Compatible with Keycloak, Entra ID, and other standards-compliant IdPs.
Discovery uses ``{issuer}/.well-known/openid-configuration``.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from .config import Settings

logger = logging.getLogger(__name__)

SESSION_OIDC_STATE = "oidc_state"
SESSION_OIDC_VERIFIER = "oidc_code_verifier"
SESSION_OIDC_NONCE = "oidc_nonce"
SESSION_AUTH = "auth"
SESSION_ID_TOKEN = "oidc_id_token"


class OidcError(Exception):
    """Raised when OIDC discovery, token exchange, or validation fails."""


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
