#!/usr/bin/env python3
"""Operator CLI to create an organization + optional membership (Master Phase 13).

Platform admins use this (or ``POST /api/tenants``) to add orgs. First public
OIDC registrant is never auto-admin and never auto-creates orgs.

Examples::

    python scripts/create_tenant.py \\
        --display-name "Acme Corp" --tenant-id tenant-acme --plan-code starter

    python scripts/create_tenant.py \\
        --display-name "Acme Corp" --plan-code standard \\
        --admin-username operator
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
from app.services import tenants as tenants_service
from app.services import users as users_service
from app.services.bootstrap import ensure_tenancy_ready
from app.services.entitlements import EntitlementError
from app.services.memberships import MembershipError
from app.services.tenants import TenantError
from app.tenancy import MEMBERSHIP_ROLE_ADMIN


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create an organization (operator CLI). "
            "Does not auto-admin first public registrant."
        )
    )
    parser.add_argument("--display-name", required=True, help="Organization name")
    parser.add_argument("--tenant-id", default=None, help="Stable tenant_id")
    parser.add_argument("--slug", default=None, help="URL-safe slug")
    parser.add_argument(
        "--plan-code",
        default="starter",
        help="Entitlements plan_code (legacy_unlimited|starter|standard)",
    )
    parser.add_argument("--notes", default=None, help="Optional notes")
    parser.add_argument(
        "--admin-user-id",
        default=None,
        help="Grant tenant admin membership to this user_id",
    )
    parser.add_argument(
        "--admin-username",
        default=None,
        help="Grant tenant admin membership to this username",
    )
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
        tenant = tenants_service.create_tenant(
            display_name=args.display_name,
            tenant_id=args.tenant_id,
            slug=args.slug,
            plan_code=args.plan_code,
            notes=args.notes,
        )
    except (TenantError, EntitlementError) as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1

    admin_user_id = args.admin_user_id
    if not admin_user_id and args.admin_username:
        user = users_service.get_user_by_username(args.admin_username)
        if user is None:
            print(
                f"error: username '{args.admin_username}' not found "
                "(bootstrap platform admin first)",
                file=sys.stderr,
            )
            return 1
        admin_user_id = user["user_id"]

    membership = None
    if admin_user_id:
        try:
            membership = memberships_service.ensure_membership(
                user_id=admin_user_id,
                tenant_id=tenant["tenant_id"],
                role=MEMBERSHIP_ROLE_ADMIN,
                upgrade_role=True,
            )
        except MembershipError as exc:
            print(f"error: {exc.message}", file=sys.stderr)
            return 1

    print("tenant ready")
    print(f"  tenant_id={tenant.get('tenant_id')}")
    print(f"  display_name={tenant.get('display_name')}")
    print(f"  slug={tenant.get('slug')}")
    print(f"  plan_code={tenant.get('plan_code')}")
    if membership:
        print(
            f"  admin_membership={membership.get('membership_id')} "
            f"user_id={membership.get('user_id')} role={membership.get('role')}"
        )
    else:
        print("  admin_membership=(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
