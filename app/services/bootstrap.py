"""Startup / CLI bootstrap helpers for tenancy (Master Phase 5–8)."""

from __future__ import annotations

import logging
from typing import Any

from ..db import DatabaseUnavailableError, get_database, ping_database
from ..tenancy import ISOLATION_ENFORCED, MIGRATION_TENANT_ID
from . import audit as audit_service
from . import cmdb_migrate
from . import field_defs_migrate
from . import memberships as memberships_service
from . import tenant_indexes
from . import tenants as tenants_service
from . import users as users_service

logger = logging.getLogger(__name__)


def ensure_tenancy_ready() -> dict[str, Any]:
    """Idempotent seed: migration tenant, indexes, backfill, typed CMDB + field defs.

    Safe when MongoDB is down — returns a structured status instead of raising.
    """
    status = ping_database()
    if not status.get("ok"):
        return {
            "ok": False,
            "error": "mongodb_unavailable",
            "detail": status.get("detail"),
        }

    try:
        db = get_database()
        tenants_service.ensure_indexes()
        users_service.ensure_indexes()
        memberships_service.ensure_indexes()
        audit_indexes = audit_service.ensure_indexes()
        tenant_idx = tenant_indexes.ensure_tenant_id_indexes(db)
        tenant = tenants_service.ensure_migration_tenant()
        backfill = tenant_indexes.backfill_null_tenant_ids(
            db, tenant_id=MIGRATION_TENANT_ID
        )
        typed_migrate = cmdb_migrate.migrate_components_to_typed(
            db, default_tenant_id=MIGRATION_TENANT_ID, remove_legacy=False
        )
        field_migrate = field_defs_migrate.migrate_custom_fields_to_cmdb(
            db, default_tenant_id=MIGRATION_TENANT_ID, remove_legacy=False
        )
        return {
            "ok": True,
            "migration_tenant_id": tenant.get("tenant_id"),
            "migration_tenant_display_name": tenant.get("display_name"),
            "tenant_id_indexes": tenant_idx,
            "audit_indexes": audit_indexes,
            "backfill": backfill,
            "typed_cmdb_migrate": typed_migrate,
            "field_defs_migrate": field_migrate,
            "isolation_enforced": ISOLATION_ENFORCED,
        }
    except DatabaseUnavailableError as exc:
        logger.warning("tenancy_bootstrap_skipped detail=%s", exc)
        return {"ok": False, "error": "mongodb_unavailable", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 — startup must not crash the app
        logger.exception("tenancy_bootstrap_failed")
        return {"ok": False, "error": "bootstrap_failed", "detail": str(exc)}
