#!/usr/bin/env python3
"""Backfill missing/null tenant_id → tenant-svrmon24-legacy (Master Phase 5).

Idempotent. Safe to re-run. Also ensures the migration tenant document exists
and tenant_id indexes are present.

Usage::

    python scripts/backfill_tenant_id.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    _ = argv
    from app.db import get_database, ping_database
    from app.services import tenant_indexes
    from app.services import tenants as tenants_service
    from app.tenancy import MIGRATION_TENANT_ID

    status = ping_database()
    if not status.get("ok"):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "mongodb_unavailable",
                    "detail": status.get("detail"),
                }
            )
        )
        return 1

    tenant = tenants_service.ensure_migration_tenant()
    db = get_database()
    indexes = tenant_indexes.ensure_tenant_id_indexes(db)
    backfill = tenant_indexes.backfill_null_tenant_ids(
        db, tenant_id=MIGRATION_TENANT_ID
    )
    print(
        json.dumps(
            {
                "ok": True,
                "migration_tenant_id": tenant.get("tenant_id"),
                "migration_tenant_display_name": tenant.get("display_name"),
                "indexes": indexes,
                "backfill": backfill,
            },
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
