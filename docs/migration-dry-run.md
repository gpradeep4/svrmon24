# Migration dry-run (Master Phase 14)

Read-only checklist before running shared-Mongo migrations. **No writes** until you intentionally run the mutate scripts below.

## Prerequisites

- MongoDB reachable (`MONGODB_URI` / `MONGODB_DB` in `.env`)
- App package importable (`python` from repo root)
- Prefer a backup / snapshot of the target database first

## Dry-run report (recommended)

```bash
python scripts/migration_dry_run.py
```

The JSON report includes:

| Field | Meaning |
| --- | --- |
| `missing_tenant_id_counts` | Docs with null/missing/empty `tenant_id` per collection |
| `typed_migrate_would_copy_estimate` | Legacy `components` rows not yet present in typed `cmdb_*` |
| `field_defs_migrate_would_copy_estimate` | Legacy custom field defs not yet in `cmdb_field_definitions` |
| `migration_tenant_present` | Whether `tenant-svrmon24-legacy` exists |
| `audit_events_count` | Current audit collection size |
| `writes` | Always `false` for this script |

Re-run until counts match expectations, then execute migrations in order.

## Execute (after dry-run review)

1. **Seed migration tenant + backfill `tenant_id`**

   ```bash
   python scripts/ensure_migration_tenant.py
   python scripts/backfill_tenant_id.py
   ```

2. **Typed CMDB copy** (legacy `components` retained by default)

   ```bash
   python scripts/migrate_components_to_typed.py
   # Only after verification:
   # python scripts/migrate_components_to_typed.py --remove-legacy
   ```

3. **Field definitions copy**

   ```bash
   python scripts/migrate_custom_fields_to_cmdb.py
   # Only after verification:
   # python scripts/migrate_custom_fields_to_cmdb.py --remove-legacy
   ```

4. **Re-run dry-run** — expect `missing_tenant_id_total=0` and copy estimates ≈ 0.

Startup (`ensure_tenancy_ready`) also runs these steps idempotently when Mongo is up; the scripts are for operator-controlled dry-run → cutover.

## Safety notes

- `component_id` stays **globally** unique (preference) — do not assume per-tenant reuse.
- Shared DB + mandatory `tenant_id` scoping — never onboard a second live org until backfill + isolation are verified.
- Diagnostics remain **SIMULATED**; migrations do not enable live probes.
- Platform admin remains CLI-only (`scripts/bootstrap_platform_admin.py`).

See also: [`docs/release-hardening.md`](release-hardening.md) for Basic auth cutover after OIDC + migration verification.
