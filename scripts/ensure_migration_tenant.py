#!/usr/bin/env python3
"""Idempotent seed for the migration tenant ``SVRMON24 Legacy``.

Also ensures Phase-4 tenancy indexes (``tenant_id`` prep indexes on CMDB
collections). Safe to re-run.

Usage::

    python scripts/ensure_migration_tenant.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.bootstrap import ensure_tenancy_ready


def main() -> int:
    result = ensure_tenancy_ready()
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
