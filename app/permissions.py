"""Tenant-scoped RBAC permission matrix (roles + permissions).

Roles (SaaS defaults): ``viewer`` | ``member`` | ``admin`` | ``owner``.

Platform admin is a separate user flag (CLI bootstrap or first OIDC user when no
admin exists) and grants every permission across tenants where authorized.

Membership roles may use built-in ``viewer|member|admin|owner`` or tenant custom
roles ``custom:<role_key>`` backed by ``custom_roles`` documents.

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
    """Normalize built-in roles only (viewer|member|admin|owner)."""
    if role is None:
        return None
    value = str(role).strip().lower()
    if not value:
        return None
    if value not in MEMBERSHIP_ROLES:
        raise ValueError(f"Invalid membership role '{role}'")
    return value


def normalize_membership_role(role: str | None, *, tenant_id: str | None = None) -> str:
    """Normalize built-in or custom ``custom:<role_key>`` membership roles."""
    from .services import custom_roles as custom_roles_service

    if role is None:
        raise ValueError("role is required")
    value = str(role).strip().lower()
    if not value:
        raise ValueError("role is required")
    if value in MEMBERSHIP_ROLES:
        return value
    if custom_roles_service.is_custom_role(value):
        if not tenant_id:
            raise ValueError(f"tenant_id required for custom role '{value}'")
        key = custom_roles_service.custom_role_key(value)
        doc = custom_roles_service.get_custom_role(tenant_id, key)
        if doc is None:
            raise ValueError(f"Unknown custom role '{value}' in tenant '{tenant_id}'")
        return value
    raise ValueError(
        f"Invalid membership role '{role}' "
        "(expected viewer|member|admin|owner or custom:<role_key>)"
    )


def permissions_for_role(
    role: str | None, *, tenant_id: str | None = None
) -> frozenset[str]:
    """Return the permission set for a tenant membership role."""
    if role is None:
        return frozenset()
    value = str(role).strip().lower()
    if not value:
        return frozenset()
    if value in MEMBERSHIP_ROLES:
        return _ROLE_PERMISSIONS.get(value, frozenset())
    if value.startswith("custom:"):
        if not tenant_id:
            return frozenset()
        from .services import custom_roles as custom_roles_service

        doc = custom_roles_service.get_custom_role_by_membership_role(tenant_id, value)
        if not doc:
            return frozenset()
        perms = doc.get("permissions") or []
        return frozenset(str(p) for p in perms if p in ALL_PERMISSIONS)
    return frozenset()


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
    return permissions_for_role(role, tenant_id=tenant.tenant_id)


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


def _role_rank(role: str | None, *, tenant_id: str | None = None) -> int:
    if not role:
        return 0
    value = str(role).strip().lower()
    if value in ROLE_RANK:
        return ROLE_RANK[value]
    if value.startswith("custom:"):
        if not tenant_id:
            return 15
        from .services import custom_roles as custom_roles_service

        doc = custom_roles_service.get_custom_role_by_membership_role(tenant_id, value)
        if not doc:
            return 0
        perms = doc.get("permissions") or []
        if PERM_USERS_ADMIN in perms or PERM_ORG_ADMIN in perms:
            return ROLE_RANK[MEMBERSHIP_ROLE_ADMIN]
        if PERM_CMDB_WRITE in perms or PERM_CONFIG_WRITE in perms:
            return ROLE_RANK[MEMBERSHIP_ROLE_MEMBER]
        return ROLE_RANK[MEMBERSHIP_ROLE_VIEWER]
    return 0


def can_assign_role(*, actor: TenantContext, target_role: str) -> bool:
    """Whether ``actor`` may grant ``target_role`` in the current tenant."""
    try:
        target = normalize_membership_role(target_role, tenant_id=actor.tenant_id)
    except ValueError:
        return False
    if actor.is_platform_admin:
        return True
    if not has_permission(actor, PERM_USERS_ADMIN):
        return False
    if target == MEMBERSHIP_ROLE_OWNER:
        return has_permission(actor, PERM_ORG_ADMIN)
    actor_role = effective_role(actor)
    actor_rank = _role_rank(actor_role, tenant_id=actor.tenant_id)
    target_rank = _role_rank(target, tenant_id=actor.tenant_id)
    return actor_rank >= target_rank and actor_rank >= ROLE_RANK[MEMBERSHIP_ROLE_ADMIN]


def role_matrix(*, tenant_id: str | None = None) -> dict[str, list[str]]:
    matrix = {role: sorted(perms) for role, perms in _ROLE_PERMISSIONS.items()}
    if tenant_id:
        from .services import custom_roles as custom_roles_service

        for doc in custom_roles_service.list_custom_roles(tenant_id):
            key = str(doc.get("membership_role") or "")
            perms = doc.get("permissions") or []
            if key:
                matrix[key] = sorted(str(p) for p in perms)
    return matrix


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
        "matrix": role_matrix(tenant_id=tenant.tenant_id),
        "current": {
            "tenant_id": tenant.tenant_id,
            "membership_role": tenant.membership_role,
            "effective_role": effective_role(tenant),
            "is_platform_admin": tenant.is_platform_admin,
            "auth_method": tenant.auth_user.auth_method,
            "permissions": perms,
        },
        "notes": (
            "Tenant-scoped RBAC. Platform admin is CLI bootstrap or first OIDC user "
            "when no admin exists. HTTP Basic uses an effective admin role on the "
            "migration tenant only."
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
