#!/usr/bin/env python3
"""Promote or demote a tenant membership role (RBAC operator CLI).

Use this when a user needs ``audit:read`` (admin/owner) or other elevated
tenant permissions. Platform admin remains a separate flag via
``scripts/bootstrap_platform_admin.py``.

Examples::

    # By username on the migration tenant
    python scripts/set_membership_role.py \\
        --username alice --role admin

    # Explicit tenant + user id
    python scripts/set_membership_role.py \\
        --tenant-id tenant-acme --user-id usr_... --role owner
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import ping_database
from app.services import memberships as memberships_service
from app.services import users as users_service
from app.services.bootstrap import ensure_tenancy_ready
from app.services.memberships import MembershipError
from app.tenancy import MEMBERSHIP_ROLES, MIGRATION_TENANT_ID


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Set a tenant membership role (viewer|member|admin|owner)"
    )
    parser.add_argument(
        "--tenant-id",
        default=MIGRATION_TENANT_ID,
        help=f"Tenant id (default: {MIGRATION_TENANT_ID})",
    )
    parser.add_argument(
        "--role",
        required=True,
        choices=sorted(MEMBERSHIP_ROLES),
        help="Target membership role",
    )
    ident = parser.add_mutually_exclusive_group(required=True)
    ident.add_argument("--username", help="Local username to look up")
    ident.add_argument("--user-id", help="Local user_id")
    ident.add_argument("--membership-id", help="Existing membership_id")
    args = parser.parse_args(argv)

    db = ping_database()
    if not db.get("ok"):
        print(f"error: MongoDB unavailable: {db.get('detail')}", file=sys.stderr)
        return 1

    ready = ensure_tenancy_ready()
    if not ready.get("ok"):
        print(f"error: tenancy bootstrap failed: {ready.get('detail')}", file=sys.stderr)
        return 1

    try:
        if args.membership_id:
            membership = memberships_service.update_membership_role(
                membership_id=args.membership_id,
                role=args.role,
            )
        else:
            user = None
            if args.user_id:
                user = users_service.get_user(args.user_id)
            elif args.username:
                user = users_service.get_user_by_username(args.username)
            if user is None:
                print("error: user not found", file=sys.stderr)
                return 1
            existing = memberships_service.get_membership_for_user_tenant(
                user["user_id"], args.tenant_id
            )
            if existing is None:
                membership = memberships_service.create_membership(
                    user_id=user["user_id"],
                    tenant_id=args.tenant_id,
                    role=args.role,
                )
            else:
                membership = memberships_service.update_membership_role(
                    membership_id=str(existing["membership_id"]),
                    role=args.role,
                )
    except MembershipError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — operator CLI surface
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("membership role updated")
    print(f"  membership_id={membership.get('membership_id')}")
    print(f"  tenant_id={membership.get('tenant_id')}")
    print(f"  user_id={membership.get('user_id')}")
    print(f"  role={membership.get('role')}")
    if membership.get("role") in {"admin", "owner"}:
        print("  note: role includes audit:read — Audit Logs UI will load after re-login/refresh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
