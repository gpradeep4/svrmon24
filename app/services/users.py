"""Local user / identity persistence linked to OIDC (Master Phase 4).

Platform admin is **never** granted on first public OIDC login. Only the
operator CLI bootstrap path may set ``is_platform_admin=True``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from ..db import require_database
from ..serialization import serialize_document

COLLECTION = "users"


class UserError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _collection() -> Collection:
    coll = require_database()[COLLECTION]
    coll.create_index([("user_id", ASCENDING)], unique=True)
    # OIDC identity is unique per issuer+subject when subject is present.
    coll.create_index(
        [("oidc_issuer", ASCENDING), ("oidc_subject", ASCENDING)],
        unique=True,
        partialFilterExpression={
            "oidc_subject": {"$type": "string"},
            "oidc_issuer": {"$type": "string"},
        },
        name="oidc_issuer_subject_unique",
    )
    coll.create_index([("email", ASCENDING)])
    coll.create_index([("username", ASCENDING)])
    coll.create_index([("is_platform_admin", ASCENDING)])
    return coll


def ensure_indexes() -> None:
    _collection()


def generate_user_id() -> str:
    return f"user-{uuid.uuid4().hex[:12]}"


def get_user(user_id: str) -> dict[str, Any] | None:
    doc = _collection().find_one({"user_id": user_id})
    return serialize_document(doc)  # type: ignore[return-value]


def get_user_by_oidc(issuer: str, subject: str) -> dict[str, Any] | None:
    if not issuer or not subject:
        return None
    doc = _collection().find_one({"oidc_issuer": issuer, "oidc_subject": subject})
    return serialize_document(doc)  # type: ignore[return-value]


def get_user_by_username(username: str) -> dict[str, Any] | None:
    doc = _collection().find_one({"username": username})
    return serialize_document(doc)  # type: ignore[return-value]


def get_user_by_email(email: str) -> dict[str, Any] | None:
    if not email:
        return None
    doc = _collection().find_one({"email": email.lower()})
    return serialize_document(doc)  # type: ignore[return-value]


def ensure_user_from_oidc(
    *,
    issuer: str,
    subject: str,
    username: str,
    email: str | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Upsert a local user from an OIDC login.

    **Never** sets ``is_platform_admin``. New users default to ``False``.
    Existing platform-admin flag is preserved (CLI bootstrap only).
    """
    if not issuer or not subject:
        raise UserError("OIDC issuer and subject are required", status_code=422)
    if not username:
        raise UserError("username is required", status_code=422)

    coll = _collection()
    now = _now()
    existing = coll.find_one({"oidc_issuer": issuer, "oidc_subject": subject})
    email_norm = email.lower().strip() if email else None

    if existing is not None:
        updates: dict[str, Any] = {
            "username": username,
            "updated_at": now,
            "last_login_at": now,
        }
        if email_norm:
            updates["email"] = email_norm
        if display_name:
            updates["display_name"] = display_name
        # Explicitly do NOT touch is_platform_admin on login.
        coll.update_one({"user_id": existing["user_id"]}, {"$set": updates})
        doc = coll.find_one({"user_id": existing["user_id"]})
        return serialize_document(doc)  # type: ignore[return-value]

    doc = {
        "user_id": generate_user_id(),
        "username": username,
        "email": email_norm,
        "display_name": display_name or username,
        "oidc_issuer": issuer,
        "oidc_subject": subject,
        "is_platform_admin": False,
        "created_at": now,
        "updated_at": now,
        "last_login_at": now,
    }
    try:
        coll.insert_one(doc)
    except DuplicateKeyError as exc:
        # Race: another request created the same OIDC identity.
        existing = coll.find_one({"oidc_issuer": issuer, "oidc_subject": subject})
        if existing is None:
            raise UserError("Failed to create user identity", status_code=409) from exc
        return serialize_document(existing)  # type: ignore[return-value]
    return serialize_document(doc)  # type: ignore[return-value]


def bootstrap_platform_admin(
    *,
    username: str,
    email: str | None = None,
    display_name: str | None = None,
    oidc_issuer: str | None = None,
    oidc_subject: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """One-time operator path to create/link a platform admin.

    Never called from OIDC login. Idempotent: re-running upgrades the same
    identity to platform admin without creating duplicates when OIDC or
    username matches.
    """
    if not username:
        raise UserError("username is required", status_code=422)

    coll = _collection()
    now = _now()
    email_norm = email.lower().strip() if email else None

    existing: dict[str, Any] | None = None
    if user_id:
        existing = coll.find_one({"user_id": user_id})
    if existing is None and oidc_issuer and oidc_subject:
        existing = coll.find_one(
            {"oidc_issuer": oidc_issuer, "oidc_subject": oidc_subject}
        )
    if existing is None and email_norm:
        existing = coll.find_one({"email": email_norm})
    if existing is None:
        existing = coll.find_one({"username": username})

    if existing is not None:
        updates: dict[str, Any] = {
            "username": username,
            "is_platform_admin": True,
            "updated_at": now,
        }
        if email_norm:
            updates["email"] = email_norm
        if display_name:
            updates["display_name"] = display_name
        if oidc_issuer:
            updates["oidc_issuer"] = oidc_issuer
        if oidc_subject:
            updates["oidc_subject"] = oidc_subject
        coll.update_one({"user_id": existing["user_id"]}, {"$set": updates})
        doc = coll.find_one({"user_id": existing["user_id"]})
        return serialize_document(doc)  # type: ignore[return-value]

    doc = {
        "user_id": user_id or generate_user_id(),
        "username": username,
        "email": email_norm,
        "display_name": display_name or username,
        "oidc_issuer": oidc_issuer,
        "oidc_subject": oidc_subject,
        "is_platform_admin": True,
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
        "bootstrap_source": "cli",
    }
    try:
        coll.insert_one(doc)
    except DuplicateKeyError as exc:
        raise UserError(
            "User already exists with conflicting unique identity",
            status_code=409,
        ) from exc
    return serialize_document(doc)  # type: ignore[return-value]
