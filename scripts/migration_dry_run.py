#!/usr/bin/env python3
"""Migration dry-run report (Master Phase 14) — read-only.

Prints counts of work that the Phase 5–7 migrations *would* touch, without
writing. Use before ``backfill_tenant_id.py``, ``migrate_components_to_typed.py``,
or ``migrate_custom_fields_to_cmdb.py`` on a shared MongoDB.

Usage::

    python scripts/migration_dry_run.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _count(coll, query: dict[str, Any]) -> int:
    return int(coll.count_documents(query))


def main(argv: list[str] | None = None) -> int:
    _ = argv
    from app.config import get_settings
    from app.db import get_database, ping_database
    from app.services.cmdb_collections import (
        collection_name_for_type,
    )
    from app.tenancy import (
        MISSING_TENANT_ID_FILTER,
        MIGRATION_TENANT_ID,
        TENANTED_COLLECTIONS,
        TYPED_CMDB_COLLECTIONS,
    )

    settings = get_settings()
    ping = ping_database(settings)
    if not ping.get("ok"):
        print(
            json.dumps(
                {
                    "ok": False,
                    "dry_run": True,
                    "error": "mongodb_unavailable",
                    "detail": ping.get("detail"),
                },
                indent=2,
            )
        )
        return 1

    db = get_database()
    missing_tenant: dict[str, int] = {}
    for name in TENANTED_COLLECTIONS:
        missing_tenant[name] = _count(db[name], MISSING_TENANT_ID_FILTER)

    legacy_components = _count(db["components"], {})
    typed_totals = {
        name: _count(db[name], {}) for name in TYPED_CMDB_COLLECTIONS
    }
    # Rough "would copy" estimate: legacy docs whose component_id is absent
    # from the typed collection for that type.
    would_copy_typed = 0
    for doc in db["components"].find({}, {"component_id": 1, "component_type": 1}):
        ctype = doc.get("component_type")
        cid = doc.get("component_id")
        if not ctype or not cid:
            continue
        try:
            target = collection_name_for_type(str(ctype))
        except ValueError:
            continue
        if db[target].count_documents({"component_id": cid}, limit=1) == 0:
            would_copy_typed += 1

    legacy_fields = _count(db["custom_field_definitions"], {})
    cmdb_fields = _count(db["cmdb_field_definitions"], {})
    would_copy_fields = 0
    for doc in db["custom_field_definitions"].find(
        {}, {"field_key": 1, "tenant_id": 1}
    ):
        key = doc.get("field_key")
        tid = doc.get("tenant_id") or MIGRATION_TENANT_ID
        if not key:
            continue
        if (
            db["cmdb_field_definitions"].count_documents(
                {"tenant_id": tid, "field_key": key}, limit=1
            )
            == 0
        ):
            would_copy_fields += 1

    migration_tenant = db["tenants"].find_one({"tenant_id": MIGRATION_TENANT_ID})
    audit_count = _count(db["audit_events"], {})

    report = {
        "ok": True,
        "dry_run": True,
        "writes": False,
        "database": settings.mongodb_db,
        "migration_tenant_id": MIGRATION_TENANT_ID,
        "migration_tenant_present": bool(migration_tenant),
        "missing_tenant_id_counts": missing_tenant,
        "missing_tenant_id_total": sum(missing_tenant.values()),
        "legacy_components_count": legacy_components,
        "typed_collection_counts": typed_totals,
        "typed_migrate_would_copy_estimate": would_copy_typed,
        "legacy_custom_field_definitions": legacy_fields,
        "cmdb_field_definitions": cmdb_fields,
        "field_defs_migrate_would_copy_estimate": would_copy_fields,
        "audit_events_count": audit_count,
        "next_steps": [
            "Review missing_tenant_id_counts; then: python scripts/backfill_tenant_id.py",
            "Review typed_migrate_would_copy_estimate; then: python scripts/migrate_components_to_typed.py",
            "Review field_defs_migrate_would_copy_estimate; then: python scripts/migrate_custom_fields_to_cmdb.py",
            "Only after verification: migrate_components_to_typed.py --remove-legacy / migrate_custom_fields_to_cmdb.py --remove-legacy",
            "Keep BASIC_AUTH_ENABLED=false in production until OIDC+migration cutover is complete (see docs/release-hardening.md)",
        ],
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
