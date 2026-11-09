"""Tenant-scoped RBAC permission matrix (roles + permissions).

Roles (SaaS defaults): ``viewer`` | ``member`` | ``admin`` | ``owner``.

Platform admin is a separate user flag (CLI bootstrap only) and grants every
permission across tenants where the caller is authorized to act.

HTTP Basic migration sessions have no membership role; they receive an effective
``admin`` permission set on the migration tenant so existing migration tooling
keeps working (still hard-scoped — never a cross-tenant bypass).
"""

from __future__ import annotations

from typing import Any, Iterable

from fastapi import Depends, HTTPException, status

from .tenancy import (
    MEMBERSHIP_ROLE_ADMIN,
    MEMBERSHIP_ROLE_MEMBER,
    MEMBERSHIP_ROLE_OWNER,
    MEMBERSHIP_ROLE_VIEWER,
    MEMBERSHIP_ROLES,
)
from .tenant_context import TenantContext, require_tenant

# ---------------------------------------------------------------------------
# Permission identifiers
# ---------------------------------------------------------------------------

PERM_CMDB_READ = "cmdb:read"
PERM_CMDB_WRITE = "cmdb:write"
PERM_RELATIONSHIPS_READ = "relationships:read"
PERM_RELATIONSHIPS_WRITE = "relationships:write"
PERM_DIAGNOSTICS_READ = "diagnostics:read"
PERM_DIAGNOSTICS_RUN = "diagnostics:run"
PERM_CONFIG_READ = "config:read"
PERM_CONFIG_WRITE = "config:write"
PERM_USERS_READ = "users:read"
PERM_USERS_ADMIN = "users:admin"
PERM_ORG_ADMIN = "org:admin"
PERM_AUDIT_READ = "audit:read"
PERM_PLANS_READ = "plans:read"
PERM_PLANS_ADMIN = "plans:admin"

ALL_PERMISSIONS: tuple[str, ...] = (
    PERM_CMDB_READ,
    PERM_CMDB_WRITE,
    PERM_RELATIONSHIPS_READ,
    PERM_RELATIONSHIPS_WRITE,
    PERM_DIAGNOSTICS_READ,
    PERM_DIAGNOSTICS_RUN,
    PERM_CONFIG_READ,
    PERM_CONFIG_WRITE,
    PERM_USERS_READ,
    PERM_USERS_ADMIN,
    PERM_ORG_ADMIN,
    PERM_AUDIT_READ,
    PERM_PLANS_READ,
    PERM_PLANS_ADMIN,
)

PERMISSION_LABELS: dict[str, str] = {
    PERM_CMDB_READ: "Read CMDB inventory / custom records",
    PERM_CMDB_WRITE: "Create / update / delete CMDB + custom records",
    PERM_RELATIONSHIPS_READ: "Read relationships + dependency graphs",
    PERM_RELATIONSHIPS_WRITE: "Create / update / delete relationships",
    PERM_DIAGNOSTICS_READ: "Read diagnostic history",
    PERM_DIAGNOSTICS_RUN: "Run SIMULATED diagnostics + AI analysis",
    PERM_CONFIG_READ: "Read field defs / column configs / custom table schemas",
    PERM_CONFIG_WRITE: "Write field defs / column configs / custom table schemas",
    PERM_USERS_READ: "List organization members",
    PERM_USERS_ADMIN: "Add / update memberships (non-owner roles)",
    PERM_ORG_ADMIN: "Organization ownership (grant owner role)",
    PERM_AUDIT_READ: "Read tenant audit events",
    PERM_PLANS_READ: "Read entitlements / plan catalog",
    PERM_PLANS_ADMIN: "Assign tenant plan_code (platform admin)",
}

# Role → permissions (tenant-scoped). Platform admin gets the full set separately.
_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    MEMBERSHIP_ROLE_VIEWER: frozenset(
        {
            PERM_CMDB_READ,
            PERM_RELATIONSHIPS_READ,
            PERM_DIAGNOSTICS_READ,
            PERM_CONFIG_READ,
            PERM_PLANS_READ,
        }
    ),
    MEMBERSHIP_ROLE_MEMBER: frozenset(
        {
            PERM_CMDB_READ,
            PERM_CMDB_WRITE,
            PERM_RELATIONSHIPS_READ,
            PERM_RELATIONSHIPS_WRITE,
            PERM_DIAGNOSTICS_READ,
            PERM_DIAGNOSTICS_RUN,
            PERM_CONFIG_READ,
            PERM_PLANS_READ,
        }
    ),
    MEMBERSHIP_ROLE_ADMIN: frozenset(
        {
            PERM_CMDB_READ,
            PERM_CMDB_WRITE,
            PERM_RELATIONSHIPS_READ,
            PERM_RELATIONSHIPS_WRITE,
            PERM_DIAGNOSTICS_READ,
            PERM_DIAGNOSTICS_RUN,
            PERM_CONFIG_READ,
            PERM_CONFIG_WRITE,
            PERM_USERS_READ,
            PERM_USERS_ADMIN,
            PERM_AUDIT_READ,
            PERM_PLANS_READ,
        }
    ),
    MEMBERSHIP_ROLE_OWNER: frozenset(
        {
            PERM_CMDB_READ,
            PERM_CMDB_WRITE,
            PERM_RELATIONSHIPS_READ,
            PERM_RELATIONSHIPS_WRITE,
            PERM_DIAGNOSTICS_READ,
            PERM_DIAGNOSTICS_RUN,
            PERM_CONFIG_READ,
            PERM_CONFIG_WRITE,
            PERM_USERS_READ,
            PERM_USERS_ADMIN,
            PERM_ORG_ADMIN,
            PERM_AUDIT_READ,
            PERM_PLANS_READ,
        }
    ),
}

ROLE_RANK: dict[str, int] = {
    MEMBERSHIP_ROLE_VIEWER: 10,
    MEMBERSHIP_ROLE_MEMBER: 20,
    MEMBERSHIP_ROLE_ADMIN: 30,
    MEMBERSHIP_ROLE_OWNER: 40,
}

# Basic migration sessions: admin-equivalent inside the migration tenant only.
BASIC_EFFECTIVE_ROLE = MEMBERSHIP_ROLE_ADMIN


def normalize_role(role: str | None) -> str | None:
    if role is None:
        return None
    value = str(role).strip().lower()
    if not value:
        return None
    if value not in MEMBERSHIP_ROLES:
        raise ValueError(f"Invalid membership role '{role}'")
    return value


def permissions_for_role(role: str | None) -> frozenset[str]:
    """Return the permission set for a tenant membership role."""
    if role is None:
        return frozenset()
    try:
        norm = normalize_role(role)
    except ValueError:
        return frozenset()
    if norm is None:
        return frozenset()
    return _ROLE_PERMISSIONS.get(norm, frozenset())


def effective_role(tenant: TenantContext) -> str | None:
    """Resolve the caller's effective tenant role for permission checks."""
    if tenant.is_platform_admin:
        return MEMBERSHIP_ROLE_OWNER
    if tenant.auth_user.auth_method == "basic":
        return BASIC_EFFECTIVE_ROLE
    return tenant.membership_role


def permissions_for_tenant(tenant: TenantContext) -> frozenset[str]:
    """Permissions granted to this request in the current tenant context."""
    if tenant.is_platform_admin:
        # Platform admin: full matrix including plans:admin.
        return frozenset(ALL_PERMISSIONS)
    role = effective_role(tenant)
    return permissions_for_role(role)


def has_permission(tenant: TenantContext, permission: str) -> bool:
    return permission in permissions_for_tenant(tenant)


def assert_permission(tenant: TenantContext, permission: str) -> None:
    if has_permission(tenant, permission):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"Permission '{permission}' required "
            f"(role={effective_role(tenant) or 'none'}; "
            f"platform_admin={tenant.is_platform_admin})"
        ),
    )


def require_permission(permission: str):
    """FastAPI dependency factory that enforces a single permission."""

    def _dep(
        tenant: TenantContext = Depends(require_tenant),
    ) -> TenantContext:
        assert_permission(tenant, permission)
        return tenant

    return _dep


def can_assign_role(*, actor: TenantContext, target_role: str) -> bool:
    """Whether ``actor`` may grant ``target_role`` in the current tenant."""
    try:
        target = normalize_role(target_role)
    except ValueError:
        return False
    if target is None:
        return False
    if actor.is_platform_admin:
        return True
    if not has_permission(actor, PERM_USERS_ADMIN):
        return False
    if target == MEMBERSHIP_ROLE_OWNER:
        return has_permission(actor, PERM_ORG_ADMIN)
    # Admins may assign viewer/member/admin; owners may assign any.
    actor_role = effective_role(actor)
    actor_rank = ROLE_RANK.get(actor_role or "", 0)
    target_rank = ROLE_RANK.get(target, 0)
    # May assign roles at or below own rank (owner assigns all via org:admin above).
    return actor_rank >= target_rank and actor_rank >= ROLE_RANK[MEMBERSHIP_ROLE_ADMIN]


def role_matrix() -> dict[str, list[str]]:
    return {
        role: sorted(perms)
        for role, perms in _ROLE_PERMISSIONS.items()
    }


def permission_catalog() -> list[dict[str, str]]:
    return [
        {"permission": key, "description": PERMISSION_LABELS.get(key, key)}
        for key in ALL_PERMISSIONS
    ]


def describe_for_tenant(tenant: TenantContext) -> dict[str, Any]:
    perms = sorted(permissions_for_tenant(tenant))
    return {
        "roles": sorted(MEMBERSHIP_ROLES, key=lambda r: ROLE_RANK.get(r, 0)),
        "permissions": permission_catalog(),
        "matrix": role_matrix(),
        "current": {
            "tenant_id": tenant.tenant_id,
            "membership_role": tenant.membership_role,
            "effective_role": effective_role(tenant),
            "is_platform_admin": tenant.is_platform_admin,
            "auth_method": tenant.auth_user.auth_method,
            "permissions": perms,
        },
        "notes": (
            "Tenant-scoped RBAC. Platform admin is CLI-bootstrap only and receives "
            "all permissions (including plans:admin). HTTP Basic uses an effective "
            "admin role on the migration tenant only."
        ),
    }


def assert_any_permission(tenant: TenantContext, permissions: Iterable[str]) -> None:
    wanted = list(permissions)
    if any(has_permission(tenant, p) for p in wanted):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"One of permissions {wanted} required",
    )
