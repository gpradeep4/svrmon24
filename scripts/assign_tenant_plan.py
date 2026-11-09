#!/usr/bin/env python3
"""Assign an entitlements-only plan_code to a tenant (Master Phase 13).

No payment provider — this only sets plan limits on the tenant document.

Examples::

    python scripts/assign_tenant_plan.py \\
        --tenant-id tenant-acme --plan-code standard

    python scripts/assign_tenant_plan.py \\
        --tenant-id tenant-svrmon24-legacy --plan-code legacy_unlimited
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import ping_database
from app.services import entitlements as entitlements_service
from app.services import tenants as tenants_service
from app.services.bootstrap import ensure_tenancy_ready
from app.services.entitlements import EntitlementError
from app.services.tenants import TenantError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assign entitlements plan_code (no payment provider)"
    )
    parser.add_argument("--tenant-id", required=True, help="Target tenant_id")
    parser.add_argument(
        "--plan-code",
        required=True,
        help="Plan code from catalog (legacy_unlimited|starter|standard)",
    )
    parser.add_argument(
        "--list-plans",
        action="store_true",
        help="Print catalog and exit",
    )
    args = parser.parse_args(argv)

    if args.list_plans:
        for plan in entitlements_service.list_plans():
            print(f"{plan['plan_code']}: {plan['plan_label']}")
            for key, val in sorted((plan.get("limits") or {}).items()):
                shown = "unlimited" if val is None else val
                print(f"  {key}={shown}")
        return 0

    db = ping_database()
    if not db.get("ok"):
        print(f"error: MongoDB unavailable: {db.get('detail')}", file=sys.stderr)
        return 1

    ready = ensure_tenancy_ready()
    if not ready.get("ok"):
        print(f"error: tenancy bootstrap failed: {ready.get('detail')}", file=sys.stderr)
        return 1

    try:
        tenant = tenants_service.set_tenant_plan(args.tenant_id, args.plan_code)
    except (TenantError, EntitlementError) as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1

    ents = entitlements_service.get_tenant_entitlements(tenant["tenant_id"])
    print("plan assigned")
    print(f"  tenant_id={tenant.get('tenant_id')}")
    print(f"  plan_code={ents.get('plan_code')}")
    print(f"  plan_label={ents.get('plan_label')}")
    print(f"  billing_enabled={ents.get('billing_enabled')}")
    print(f"  payment_provider={ents.get('payment_provider')}")
    for key, val in sorted((ents.get("limits") or {}).items()):
        shown = "unlimited" if val is None else val
        print(f"  limit.{key}={shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
