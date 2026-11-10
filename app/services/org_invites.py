"""Organization membership invites (email / username)."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from ..db import require_database
from ..serialization import serialize_document
from ..tenancy import MEMBERSHIP_ROLES
from . import memberships as memberships_service
from . import tenants as tenants_service
from . import users as users_service

COLLECTION = "org_invites"
DEFAULT_TTL_HOURS = 168  # 7 days


class InviteError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _collection():
    coll = require_database()[COLLECTION]
    coll.create_index([("invite_id", ASCENDING)], unique=True)
    coll.create_index([("token", ASCENDING)], unique=True)
    coll.create_index([("tenant_id", ASCENDING), ("status", ASCENDING)])
    coll.create_index([("invitee_email", ASCENDING)])
    coll.create_index([("invitee_username", ASCENDING)])
    return coll


def ensure_indexes() -> None:
    _collection()


def generate_invite_id() -> str:
    return f"inv-{uuid.uuid4().hex[:12]}"


def _normalize_email(email: str | None) -> str | None:
    if not email:
        return None
    value = email.strip().lower()
    return value or None


def _normalize_username(username: str | None) -> str | None:
    if not username:
        return None
    value = username.strip()
    return value or None


def _validate_role(role: str) -> str:
    value = (role or "").strip().lower()
    if value.startswith("custom:"):
        return value
    if value not in MEMBERSHIP_ROLES:
        raise InviteError(
            f"Invalid role '{role}' (expected viewer|member|admin|owner or custom:…)",
            status_code=422,
        )
    return value


def create_invite(
    *,
    tenant_id: str,
    role: str,
    invitee_email: str | None = None,
    invitee_username: str | None = None,
    created_by_user_id: str | None = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> dict[str, Any]:
    email = _normalize_email(invitee_email)
    username = _normalize_username(invitee_username)
    if not email and not username:
        raise InviteError(
            "invitee_email or invitee_username is required",
            status_code=422,
        )
    role_norm = _validate_role(role)
    tenant = tenants_service.get_tenant(tenant_id)
    if tenant is None:
        raise InviteError(f"Tenant '{tenant_id}' not found", status_code=404)

    now = _now()
    doc = {
        "invite_id": generate_invite_id(),
        "tenant_id": tenant_id,
        "invitee_email": email,
        "invitee_username": username,
        "role": role_norm,
        "token": secrets.token_urlsafe(32),
        "status": "pending",
        "created_by_user_id": created_by_user_id,
        "created_at": now,
        "updated_at": now,
        "expires_at": now + timedelta(hours=max(1, int(ttl_hours))),
    }
    try:
        _collection().insert_one(doc)
    except DuplicateKeyError as exc:
        raise InviteError("Failed to create invite", status_code=409) from exc
    row = serialize_document(doc)
    assert row is not None
    row["tenant_display_name"] = tenant.get("display_name")
    return row


def list_invites_for_tenant(tenant_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
    query: dict[str, Any] = {"tenant_id": tenant_id}
    if status:
        query["status"] = status
    docs = list(_collection().find(query).sort("created_at", DESCENDING))
    out: list[dict[str, Any]] = []
    tenant = tenants_service.get_tenant(tenant_id)
    for doc in docs:
        row = serialize_document(doc)
        assert row is not None
        if tenant:
            row["tenant_display_name"] = tenant.get("display_name")
        out.append(row)
    return out


def get_invite(invite_id: str) -> dict[str, Any] | None:
    doc = _collection().find_one({"invite_id": invite_id})
    return serialize_document(doc)  # type: ignore[return-value]


def get_invite_by_token(token: str) -> dict[str, Any] | None:
    doc = _collection().find_one({"token": (token or "").strip()})
    return serialize_document(doc)  # type: ignore[return-value]


def revoke_invite(invite_id: str, tenant_id: str) -> dict[str, Any]:
    coll = _collection()
    doc = coll.find_one({"invite_id": invite_id, "tenant_id": tenant_id})
    if doc is None:
        raise InviteError("Invite not found", status_code=404)
    if doc.get("status") == "accepted":
        raise InviteError("Cannot revoke an accepted invite", status_code=409)
    coll.update_one(
        {"invite_id": invite_id},
        {"$set": {"status": "revoked", "updated_at": _now()}},
    )
    refreshed = get_invite(invite_id)
    assert refreshed is not None
    return refreshed


def accept_invite(
    *,
    token: str,
    user_id: str,
    username: str,
    email: str | None,
) -> dict[str, Any]:
    invite = get_invite_by_token(token)
    if invite is None:
        raise InviteError("Invite not found", status_code=404)
    if invite.get("status") != "pending":
        raise InviteError(f"Invite is {invite.get('status')}", status_code=409)
    expires = invite.get("expires_at")
    if isinstance(expires, datetime) and expires < _now():
        _collection().update_one(
            {"invite_id": invite["invite_id"]},
            {"$set": {"status": "expired", "updated_at": _now()}},
        )
        raise InviteError("Invite has expired", status_code=410)

    email_norm = _normalize_email(email)
    username_norm = _normalize_username(username)
    invite_email = invite.get("invitee_email")
    invite_username = invite.get("invitee_username")
    email_ok = not invite_email or (email_norm and email_norm == invite_email)
    user_ok = not invite_username or (
        username_norm and username_norm.lower() == str(invite_username).lower()
    )
    if not (email_ok and user_ok):
        raise InviteError(
            "Authenticated user does not match invite email/username",
            status_code=403,
        )

    user = users_service.get_user(user_id)
    if user is None:
        raise InviteError("User not found", status_code=404)

    role = str(invite.get("role") or "member")
    membership = memberships_service.ensure_membership(
        user_id=user_id,
        tenant_id=str(invite["tenant_id"]),
        role=role,
        upgrade_role=True,
    )
    if str(membership.get("role") or "") != role:
        membership = memberships_service.update_membership_role(
            membership_id=str(membership["membership_id"]),
            role=role,
        )
    _collection().update_one(
        {"invite_id": invite["invite_id"]},
        {
            "$set": {
                "status": "accepted",
                "accepted_at": _now(),
                "accepted_by_user_id": user_id,
                "updated_at": _now(),
            }
        },
    )
    return {
        "invite_id": invite.get("invite_id"),
        "membership": membership,
        "tenant_id": invite.get("tenant_id"),
        "role": role,
    }
