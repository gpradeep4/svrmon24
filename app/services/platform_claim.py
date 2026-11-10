"""Singleton claim for first platform admin (race-safe).

Only one document may exist in ``platform_admin_claim``. The first successful
insert wins; concurrent first logins lose the claim and remain non-admin.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError

from ..db import require_database

COLLECTION = "platform_admin_claim"
CLAIM_ID = "first_platform_admin"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_indexes() -> None:
    # MongoDB collections already have a unique _id index; no extra spec needed.


def count_platform_admins() -> int:
    return int(require_database()["users"].count_documents({"is_platform_admin": True}))


def try_claim_first_platform_admin(*, user_id: str, source: str = "first_oidc_user") -> bool:
    """Atomically claim first-platform-admin when zero admins exist."""
    if not user_id:
        return False
    if count_platform_admins() > 0:
        return False

    coll = require_database()[COLLECTION]
    claim_doc: dict[str, Any] = {
        "_id": CLAIM_ID,
        "user_id": user_id,
        "source": source,
        "created_at": _now(),
    }
    try:
        coll.insert_one(claim_doc)
    except DuplicateKeyError:
        return False

    users = require_database()["users"]
    result = users.update_one(
        {"user_id": user_id, "is_platform_admin": False},
        {
            "$set": {
                "is_platform_admin": True,
                "platform_admin_source": source,
                "updated_at": _now(),
            }
        },
    )
    if result.modified_count != 1:
        # Another path promoted this user, or user missing — claim still reserved.
        doc = users.find_one({"user_id": user_id})
        return bool(doc and doc.get("is_platform_admin"))
    return True
