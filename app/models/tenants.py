"""Tenant, user identity, and membership models (Master Phase 4)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..tenancy import (
    MEMBERSHIP_ROLE_ADMIN,
    MEMBERSHIP_ROLE_MEMBER,
    MEMBERSHIP_ROLE_OWNER,
    MEMBERSHIP_ROLE_VIEWER,
    MIGRATION_TENANT_DISPLAY_NAME,
    MIGRATION_TENANT_ID,
    MIGRATION_TENANT_SLUG,
)


class TenantStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class MembershipRole(str, Enum):
    VIEWER = MEMBERSHIP_ROLE_VIEWER
    MEMBER = MEMBERSHIP_ROLE_MEMBER
    ADMIN = MEMBERSHIP_ROLE_ADMIN
    OWNER = MEMBERSHIP_ROLE_OWNER


class TenantView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: str
    display_name: str
    slug: str
    status: TenantStatus = TenantStatus.ACTIVE
    is_migration_tenant: bool = False
    switchable: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UserView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    username: str
    email: str | None = None
    display_name: str | None = None
    oidc_subject: str | None = None
    oidc_issuer: str | None = None
    is_platform_admin: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None


class MembershipView(BaseModel):
    model_config = ConfigDict(extra="ignore")

    membership_id: str
    tenant_id: str
    user_id: str
    role: MembershipRole
    tenant_display_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MembershipCreate(BaseModel):
    """Internal / operator create payload (not a public multi-org invite API)."""

    tenant_id: str = Field(default=MIGRATION_TENANT_ID)
    user_id: str
    role: MembershipRole = MembershipRole.MEMBER

    @field_validator("tenant_id")
    @classmethod
    def _non_empty_tenant(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("tenant_id is required")
        return value


def migration_tenant_defaults() -> dict[str, Any]:
    """Document shape for the idempotent migration tenant seed."""
    return {
        "tenant_id": MIGRATION_TENANT_ID,
        "display_name": MIGRATION_TENANT_DISPLAY_NAME,
        "slug": MIGRATION_TENANT_SLUG,
        "status": TenantStatus.ACTIVE.value,
        "is_migration_tenant": True,
        # Phase 13: switcher is membership-driven; migration org remains eligible.
        "switchable": True,
        "plan_code": "legacy_unlimited",
        "notes": (
            "Locked migration organization (SVRMON24 Legacy). "
            "Hard tenant isolation is enforced; org switcher works for users "
            "with multiple memberships (Master Phase 13)."
        ),
    }


TenantRoleLiteral = Literal["viewer", "member", "admin", "owner"]
