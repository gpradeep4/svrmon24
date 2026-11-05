#!/usr/bin/env python3
"""Migrate legacy ``components`` → typed ``cmdb_*`` collections (Phase 6).

Idempotent. By default leaves the legacy ``components`` collection in place
as a transitional source / rollback aid. Pass ``--remove-legacy`` only after
verification to delete the polymorphic collection contents.

Usage::

    python scripts/migrate_components_to_typed.py
    python scripts/migrate_components_to_typed.py --remove-legacy
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db import ping_database, reset_client_for_tests, get_database
from app.services.bootstrap import ensure_tenancy_ready
from app.services.cmdb_migrate import migrate_components_to_typed
from app.tenancy import MIGRATION_TENANT_ID


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate components → typed cmdb_* collections"
    )
    parser.add_argument(
        "--remove-legacy",
        action="store_true",
        help="After a clean migrate, delete all docs from legacy components",
    )
    parser.add_argument(
        "--tenant-id",
        default=MIGRATION_TENANT_ID,
        help="Default tenant_id stamped onto copies missing tenant_id",
    )
    args = parser.parse_args()

    get_settings.cache_clear()
    reset_client_for_tests()
    ping = ping_database()
    if not ping.get("ok"):
        print(json.dumps({"ok": False, "error": ping.get("detail")}), file=sys.stderr)
        return 1

    ready = ensure_tenancy_ready()
    if not ready.get("ok"):
        print(json.dumps(ready, default=str), file=sys.stderr)
        return 1

    result = migrate_components_to_typed(
        get_database(),
        default_tenant_id=args.tenant_id,
        remove_legacy=args.remove_legacy,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
