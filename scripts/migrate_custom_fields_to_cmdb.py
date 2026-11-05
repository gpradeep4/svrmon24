#!/usr/bin/env python3
"""Migrate legacy ``custom_field_definitions`` → ``cmdb_field_definitions`` (Phase 7).

Idempotent. Seeds locked built-in OS Family / OS Version and Product Type /
Product Version definitions per tenant. By default leaves the legacy collection
in place; pass ``--remove-legacy`` only after verification.

Usage::

    python scripts/migrate_custom_fields_to_cmdb.py
    python scripts/migrate_custom_fields_to_cmdb.py --remove-legacy
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
from app.db import get_database, ping_database, reset_client_for_tests
from app.services.bootstrap import ensure_tenancy_ready
from app.services.field_defs_migrate import migrate_custom_fields_to_cmdb
from app.tenancy import MIGRATION_TENANT_ID


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate custom_field_definitions → cmdb_field_definitions"
    )
    parser.add_argument(
        "--remove-legacy",
        action="store_true",
        help="After a clean migrate, delete all docs from legacy custom_field_definitions",
    )
    args = parser.parse_args()

    get_settings.cache_clear()
    status = ping_database()
    if not status.get("ok"):
        print(json.dumps({"ok": False, "error": "mongodb_unavailable", "detail": status}))
        return 1

    ready = ensure_tenancy_ready()
    db = get_database()
    result = migrate_custom_fields_to_cmdb(
        db,
        default_tenant_id=MIGRATION_TENANT_ID,
        remove_legacy=args.remove_legacy,
    )
    result["tenancy_ready"] = ready.get("ok")
    print(json.dumps(result, default=str, indent=2))
    reset_client_for_tests()
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
