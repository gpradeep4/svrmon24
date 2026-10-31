#!/usr/bin/env python3
"""One-time CLI bootstrap for a platform admin operator (Master Phase 4).

Platform admin is **never** granted automatically on first public OIDC login.
Use this script (operator-only) to create or upgrade a local user with
``is_platform_admin=True`` and optionally a tenant ``admin`` membership on the
migration tenant ``SVRMON24 Legacy``.

Examples::

    python scripts/bootstrap_platform_admin.py \\
        --username operator --email ops@example.com

    python scripts/bootstrap_platform_admin.py \\
        --username operator --email ops@example.com \\
        --oidc-issuer http://localhost:8080/realms/svrmon24 \\
        --oidc-subject abc-123 \\
        --tenant-role admin
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
from app.services.users import UserError
from app.tenancy import (
    MEMBERSHIP_ROLE_ADMIN,
    MEMBERSHIP_ROLE_MEMBER,
    MIGRATION_TENANT_ID,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap a platform admin (CLI/operator only). "
            "Never auto-admin first public OIDC registrant."
        )
    )
    parser.add_argument("--username", required=True, help="Local username")
    parser.add_argument("--email", default=None, help="Email (optional)")
    parser.add_argument("--display-name", default=None, help="Display name")
    parser.add_argument("--oidc-issuer", default=None, help="OIDC issuer to link")
    parser.add_argument("--oidc-subject", default=None, help="OIDC subject (sub)")
    parser.add_argument("--user-id", default=None, help="Existing user_id to upgrade")
    parser.add_argument(
        "--tenant-role",
        choices=[MEMBERSHIP_ROLE_MEMBER, MEMBERSHIP_ROLE_ADMIN],
        default=MEMBERSHIP_ROLE_ADMIN,
        help="Membership role on migration tenant (default: admin)",
    )
    parser.add_argument(
        "--skip-membership",
        action="store_true",
        help="Only set is_platform_admin; do not create tenant membership",
    )
    args = parser.parse_args(argv)

    if bool(args.oidc_issuer) ^ bool(args.oidc_subject):
        print(
            "error: --oidc-issuer and --oidc-subject must be provided together",
            file=sys.stderr,
        )
        return 2

    db = ping_database()
    if not db.get("ok"):
        print(f"error: MongoDB unavailable: {db.get('detail')}", file=sys.stderr)
        return 1

    ready = ensure_tenancy_ready()
    if not ready.get("ok"):
        print(f"error: tenancy bootstrap failed: {ready.get('detail')}", file=sys.stderr)
        return 1

    try:
        user = users_service.bootstrap_platform_admin(
            username=args.username,
            email=args.email,
            display_name=args.display_name,
            oidc_issuer=args.oidc_issuer,
            oidc_subject=args.oidc_subject,
            user_id=args.user_id,
        )
    except UserError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1

    membership = None
    if not args.skip_membership:
        tenants_service.ensure_migration_tenant()
        membership = memberships_service.ensure_membership(
            user_id=user["user_id"],
            tenant_id=MIGRATION_TENANT_ID,
            role=args.tenant_role,
            upgrade_role=(args.tenant_role == MEMBERSHIP_ROLE_ADMIN),
        )

    print("platform admin ready")
    print(f"  user_id={user.get('user_id')}")
    print(f"  username={user.get('username')}")
    print(f"  email={user.get('email')}")
    print(f"  is_platform_admin={user.get('is_platform_admin')}")
    print(f"  oidc_issuer={user.get('oidc_issuer')}")
    print(f"  oidc_subject={user.get('oidc_subject')}")
    if membership:
        print(
            f"  membership={membership.get('membership_id')} "
            f"tenant={membership.get('tenant_id')} role={membership.get('role')}"
        )
    else:
        print("  membership=(skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
