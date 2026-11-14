"""Platform-level OIDC operator configuration (secrets by env reference only).

Stores non-secret IdP fields in MongoDB. Client secrets are never written here;
operators set ``client_secret_env_ref`` to an environment variable name whose
value the process reads at runtime (for example ``OIDC_CLIENT_SECRET``).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING

from ..config import Settings
from ..db import DatabaseUnavailableError, require_database
from ..serialization import serialize_document

COLLECTION = "platform_settings"
DOC_KEY = "oidc"

_ENV_REF_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class PlatformOidcError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _collection():
    return require_database()[COLLECTION]


def ensure_indexes() -> None:
    coll = _collection()
    coll.create_index([("setting_key", ASCENDING)], unique=True)


@dataclass(frozen=True)
class OidcRuntime:
    enabled: bool
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: str
    client_secret_env_ref: str | None = None
    configured_in_db: bool = False


def _normalize_env_ref(value: str | None) -> str | None:
    if not value:
        return None
    ref = value.strip()
    if not ref:
        return None
    if not _ENV_REF_RE.match(ref):
        raise PlatformOidcError(
            f"client_secret_env_ref must match { _ENV_REF_RE.pattern }",
            status_code=422,
        )
    return ref


def get_stored_oidc() -> dict[str, Any] | None:
    try:
        doc = _collection().find_one({"setting_key": DOC_KEY})
    except DatabaseUnavailableError:
        return None
    if not doc:
        return None
    return serialize_document(doc)  # type: ignore[return-value]


def resolve_client_secret(settings: Settings, env_ref: str | None) -> str:
    if env_ref:
        from_env = os.getenv(env_ref, "").strip()
        if from_env:
            return from_env
    return (settings.oidc_client_secret or "").strip()


def resolve_oidc_runtime(settings: Settings) -> OidcRuntime:
    stored = get_stored_oidc() or {}
    use_db = bool(stored.get("active"))
    issuer = (
        str(stored.get("issuer") or "").strip()
        if use_db and stored.get("issuer")
        else (settings.oidc_issuer or "").strip()
    )
    client_id = (
        str(stored.get("client_id") or "").strip()
        if use_db and stored.get("client_id")
        else (settings.oidc_client_id or "").strip()
    )
    redirect_uri = (
        str(stored.get("redirect_uri") or "").strip()
        if use_db and stored.get("redirect_uri")
        else (settings.oidc_redirect_uri or "").strip()
    )
    scopes = (
        str(stored.get("scopes") or "").strip()
        if use_db and stored.get("scopes")
        else (settings.oidc_scopes or "openid profile email").strip()
    )
    enabled = (
        bool(stored.get("oidc_enabled"))
        if use_db and stored.get("oidc_enabled") is not None
        else bool(settings.oidc_enabled)
    )
    env_ref = None
    if use_db:
        try:
            env_ref = _normalize_env_ref(stored.get("client_secret_env_ref"))
        except PlatformOidcError:
            env_ref = None
    secret = resolve_client_secret(settings, env_ref)
    return OidcRuntime(
        enabled=enabled,
        issuer=issuer,
        client_id=client_id,
        client_secret=secret,
        redirect_uri=redirect_uri,
        scopes=scopes,
        client_secret_env_ref=env_ref,
        configured_in_db=use_db,
    )


def public_oidc_settings(settings: Settings) -> dict[str, Any]:
    """Safe operator view — never includes secret values."""
    runtime = resolve_oidc_runtime(settings)
    stored = get_stored_oidc() or {}
    return {
        "oidc_enabled": runtime.enabled,
        "issuer": runtime.issuer,
        "client_id": runtime.client_id,
        "redirect_uri": runtime.redirect_uri,
        "scopes": runtime.scopes,
        "client_secret_env_ref": runtime.client_secret_env_ref,
        "client_secret_configured": bool(runtime.client_secret),
        "active_db_config": bool(stored.get("active")),
        "updated_at": stored.get("updated_at"),
        "notes": (
            "Set client_secret_env_ref to an environment variable name; never paste "
            "secrets into this UI. When active_db_config is true, non-secret fields "
            "override environment defaults."
        ),
    }


def upsert_oidc_settings(
    *,
    oidc_enabled: bool | None = None,
    issuer: str | None = None,
    client_id: str | None = None,
    redirect_uri: str | None = None,
    scopes: str | None = None,
    client_secret_env_ref: str | None = None,
    active: bool = True,
) -> dict[str, Any]:
    coll = _collection()
    now = _now()
    existing = coll.find_one({"setting_key": DOC_KEY}) or {}
    payload: dict[str, Any] = {
        "setting_key": DOC_KEY,
        "active": bool(active),
        "updated_at": now,
    }
    if not existing.get("created_at"):
        payload["created_at"] = now
    else:
        payload["created_at"] = existing.get("created_at")

    if oidc_enabled is not None:
        payload["oidc_enabled"] = bool(oidc_enabled)
    elif existing.get("oidc_enabled") is not None:
        payload["oidc_enabled"] = existing.get("oidc_enabled")

    for field, value in (
        ("issuer", issuer),
        ("client_id", client_id),
        ("redirect_uri", redirect_uri),
        ("scopes", scopes),
    ):
        if value is not None:
            cleaned = str(value).strip()
            if not cleaned and field in ("issuer", "client_id", "redirect_uri"):
                raise PlatformOidcError(f"{field} cannot be empty", status_code=422)
            payload[field] = cleaned
        elif field in existing:
            payload[field] = existing[field]

    if client_secret_env_ref is not None:
        ref = _normalize_env_ref(client_secret_env_ref) if client_secret_env_ref else None
        payload["client_secret_env_ref"] = ref
    elif "client_secret_env_ref" in existing:
        payload["client_secret_env_ref"] = existing.get("client_secret_env_ref")

    coll.update_one({"setting_key": DOC_KEY}, {"$set": payload}, upsert=True)
    doc = coll.find_one({"setting_key": DOC_KEY})
    return serialize_document(doc)  # type: ignore[return-value]
