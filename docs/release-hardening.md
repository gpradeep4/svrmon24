# Release hardening + Basic auth cutover (Master Phase 14)

SVRMON24 **0.29.0** closes the 14-phase master roadmap. This note is the operator checklist for a production-oriented cutover. It does **not** silently remove HTTP Basic — Basic stays behind `BASIC_AUTH_ENABLED` until the gates below are green.

## Release checklist

- [ ] `.env` copied from `.env.example`; **no** committed secrets
- [ ] `SESSION_SECRET` changed from placeholder
- [ ] `OIDC_ENABLED=true` with real `OIDC_ISSUER` / `CLIENT_ID` / `CLIENT_SECRET` / `OIDC_REDIRECT_URI`
- [ ] Browser always uses the **same host** as `OIDC_REDIRECT_URI` (localhost ≠ 127.0.0.1)
- [ ] `BASIC_AUTH_ENABLED=false` (production default) unless actively migrating
- [ ] MongoDB reachable; `python scripts/migration_dry_run.py` reviewed
- [ ] Migration tenant present: `tenant-svrmon24-legacy` / **SVRMON24 Legacy**
- [ ] `missing_tenant_id_total=0` after backfill
- [ ] Typed CMDB + field-def migrations verified (legacy retained until sign-off)
- [ ] Platform admin bootstrapped via CLI only — never via first public OIDC login
- [ ] Org switcher smoke: multi-membership OIDC user can switch; Basic **cannot**
- [ ] Cross-tenant denial: foreign `component_id` / relationship / diagnostic / audit → **404**
- [ ] Audit Logs UI / `GET /api/audit-events` shows mutating actions for the current tenant
- [ ] Diagnostics remain **SIMULATED**; `OLLAMA_ENABLED=false` unless intentionally on
- [ ] Plans are entitlements-only (`billing_enabled=false`); no payment provider
- [ ] **Full pytest suite** green locally or via CI (`make test` or `python -m pytest -v`) — see [`docs/ci-release-gate.md`](ci-release-gate.md)
- [ ] Targeted Phase 14 security tests pass (`pytest tests/test_phase14_audit_security.py -q`) — fast operator spot-check; CI still runs everything
- [ ] Version banner / `/health` report `0.29.0`

## Basic auth removal path (document, do not silent-delete)

Preferences: Basic must **not** bypass tenant auth; remove **after** OIDC + migration tests.

| Stage | Flag / behavior | When |
| --- | --- | --- |
| A — Coexistence | `BASIC_AUTH_ENABLED=true` allowed for migration/testing; always scoped to migration tenant | Local / cutover window only |
| B — Production default | `BASIC_AUTH_ENABLED=false` (`.env.example` default) | Before shared/prod deploy |
| C — Verify OIDC+migration | OIDC happy path + negatives; dry-run + backfill; isolation tests | Gate for Stage D |
| D — Code removal (future) | Delete Basic routes/credentials/UI only after Stage C signed off | **Explicit follow-up PR** — not part of silent Phase 14 merge |

**Phase 14 keeps Basic code paths** behind the feature flag so operators can finish migration. Cutting the flag off in config is the production posture; deleting the code is a separate, intentional change after Stage C.

### Stage C verification commands

```bash
# Auth negatives + cross-tenant denial (Phase 14 suite)
pytest tests/test_phase14_audit_security.py -q

# Migration dry-run (read-only)
python scripts/migration_dry_run.py

# Optional coexistence check: temporarily enable Basic, confirm migration-tenant scope,
# then set BASIC_AUTH_ENABLED=false again before shared use.
```

## Security hardening reminders

- Audit collection: `audit_events` (tenant-scoped list/get)
- Sensitive mutating admin/tenant/CMDB actions are recorded best-effort (Mongo outage must not fail the primary write)
- Shared-DB tenancy: every CMDB query still filters `tenant_id`
- No payments; platform admin remains CLI-only
- No live/remote diagnostics in SaaS v1

## Related docs

- [`docs/migration-dry-run.md`](migration-dry-run.md)
- Root [`README.md`](../README.md) — Phase 14 section + quick start
