# SVRMON24

AI-assisted infrastructure CMDB, dependency mapping, **SIMULATED** diagnostics, local Ollama analysis, and operations dashboard.

Stack: **FastAPI + Uvicorn + MongoDB (PyMongo) + provider-neutral OIDC** (HTTP Basic optional via feature flag). Diagnostics never contact remote hosts and never execute shell/SQL/network scans.

## Features (through custom entity tables / 0.18.0)

| Area | Capability |
| --- | --- |
| Auth / ops | OIDC (Auth Code + PKCE), feature-flagged HTTP Basic, `/health`, `/api/status`, structured logging |
| Tenancy | Hard `tenant_id` isolation on CMDB/relationships/field-definitions/column-configurations/custom-tables/diagnostics/dashboard; migration tenant **SVRMON24 Legacy** (`tenant-svrmon24-legacy`); Basic scoped to migration tenant (no auth bypass); org switcher still disabled |
| CMDB | Typed Mongo collections (`cmdb_servers`, `cmdb_network`, `cmdb_middleware`, `cmdb_databases`, `cmdb_applications`) behind stable `/api/components*` facade; OS Family/Version and Product Type/Version stay separate |
| Field definitions | Tenant-scoped `cmdb_field_definitions` (custom + locked built-in OS/product natives); `/api/custom-fields` facade; values still on component `custom_fields` |
| Column configurations | Tenant-scoped `cmdb_column_configurations` driving Inventory + Relationships grids (visibility / order / width / pin); locked OS/product and protocol/port columns |
| Custom entity tables | Tenant-scoped `cmdb_custom_table_definitions` + `cmdb_custom_records` (`table_key`); typed columns including **reference** fields; relationships can link custom entities via `source_table` / `target_table` |
| Relationships | HOSTED_ON / DEPENDS_ON / CONNECTS_TO / ROUTES_TO (CMDB ↔ CMDB, custom ↔ CMDB, custom ↔ custom) |
| Dependencies | Upstream / downstream traversal, cycle detection, impact (“potentially affected”) |
| Diagnostics | Approved `basic-health` profile — always `execution_mode=SIMULATED` |
| AI analysis | Local Ollama (`OLLAMA_URL` / `OLLAMA_MODEL`) with rule-based fallback |
| Dashboard | Live aggregates from MongoDB (no hardcoded counts) |

## Requirements

- Python **3.11+** (verified on Windows 11 / Python 3.13; compatible with RHEL Linux)
- MongoDB reachable via `MONGODB_URI` (app starts even if MongoDB is temporarily down)
- Optional: OIDC IdP (Keycloak locally, or Entra ID / any OIDC-compliant provider)
- Optional: local [Ollama](https://ollama.com/) for AI analysis (`llama3.2:3b` or another configured model)

## Quick start — Windows PowerShell

```powershell
cd C:\path\to\svrmon24
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env — configure OIDC (recommended) or temporarily set BASIC_AUTH_ENABLED=true
python -m app.main
```

Or with Uvicorn:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8200
```

Open `http://localhost:8200/` → sign in with SSO (OIDC) or Basic (if enabled) → use Dashboard / Inventory / Relationships / Dependencies / Diagnostics.

## Quick start — RHEL / Linux bash

```bash
cd /path/to/svrmon24
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
# Edit .env — configure OIDC (recommended) or temporarily set BASIC_AUTH_ENABLED=true
python -m app.main
```

Or:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8200
```

## Configuration

Copy `.env.example` → `.env` (never commit `.env`). Placeholders only in the example file:

| Variable | Purpose | Production-oriented default |
| --- | --- | --- |
| `OIDC_ENABLED` / `OIDC_ISSUER` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | Provider-neutral OIDC | `OIDC_ENABLED=false` until configured |
| `OIDC_REDIRECT_URI` / `OIDC_SCOPES` | Callback + scopes | `http://localhost:8200/auth/callback`, `openid profile email` |
| `SESSION_SECRET` | Signed session cookie | **change before shared use** |
| `BASIC_AUTH_ENABLED` | Feature-flag coexistence for migration/testing | **`false`** |
| `BASIC_AUTH_USERNAME` / `BASIC_AUTH_PASSWORD` | Shared Basic credentials (only when flag on) | placeholders |
| `MONGODB_URI` / `MONGODB_DB` | MongoDB connection | local defaults |
| `APP_HOST` / `APP_PORT` | Bind address | `0.0.0.0:8200` |
| `OLLAMA_URL` / `OLLAMA_MODEL` / `OLLAMA_TIMEOUT_SECONDS` | Local Ollama for AI analysis | localhost |

When Ollama is unavailable, diagnostic analysis uses a deterministic rule-based fallback. Analysis derived from simulated diagnostics is clearly labeled.

## Auth

- Public: `/`, `/health`, `/static/*`, `/api/auth/config`, `/auth/login`, `/auth/callback`, `/auth/logout`
- Protected: `/api/*` (OIDC session cookie and/or HTTP Basic when `BASIC_AUTH_ENABLED=true`)
- Browser login uses **Authorization Code + PKCE**; state/PKCE live in the signed session cookie **and** a short-lived pending cookie
- Unauthenticated users see a **dedicated full-page login** (no Operations sidebar/header chrome). After SSO/Basic, the app shell loads on Dashboard
- Authenticated top banner shows the current tenant (**SVRMON24 Legacy** + `tenant-svrmon24-legacy`); Organization switcher + Accent picker stay under **Settings** (switcher disabled / non-switchable)
- **Basic auth is disabled by default** for production-oriented deployments. Enable only for migration/testing. Basic is always scoped to the migration tenant and **must not** bypass tenant isolation.
- OIDC login links a local user + **member** membership on the migration tenant — **never** auto-admin the first public registrant. Current tenant is resolved from membership.
- Platform admin is **CLI/operator bootstrap only**: `python scripts/bootstrap_platform_admin.py --username operator --email ops@example.com`

### Tenancy (Phase 5 — hard isolation)

- Startup (and `python scripts/ensure_migration_tenant.py`) idempotently seeds `tenant-svrmon24-legacy` / **SVRMON24 Legacy**
- Startup / `python scripts/backfill_tenant_id.py` backfills missing/null `tenant_id` → `tenant-svrmon24-legacy` on typed `cmdb_*`, legacy `components`, `cmdb_field_definitions`, legacy `custom_field_definitions`, `cmdb_column_configurations`, `cmdb_relationships`, `diagnostic_history`
- Every list/get/update/delete/dashboard/deps/diag query is scoped to the current tenant; cross-tenant access returns **404**
- Writes require `tenant_id` (stamped from the session tenant)
- `component_id` remains **globally** unique; compound indexes include `tenant_id` for scoped lists
- APIs: `GET /api/tenants`, `GET /api/tenants/current`, `GET /api/tenants/{id}`, `GET /api/memberships` — org switcher remains **disabled**; `isolation_enforced=true`
- `/api/me` includes `current_tenant_id` + `current_tenant_display_name` for the header banner

### Typed CMDB (Phase 6)

- Inventory documents live in typed collections: `cmdb_servers`, `cmdb_network`, `cmdb_middleware`, `cmdb_databases`, `cmdb_applications`
- `/api/components*` remains the stable facade (service routes by `component_type`)
- Startup / `python scripts/migrate_components_to_typed.py` idempotently copies legacy `components` → typed collections (legacy retained unless `--remove-legacy`)
- Demo seed writes via the facade into typed collections; wipe clears demo rows from typed + legacy

### Field definitions (Phase 7)

- Canonical collection: `cmdb_field_definitions` (unique `(tenant_id, field_key)`)
- Startup / `python scripts/migrate_custom_fields_to_cmdb.py` copies legacy `custom_field_definitions` → `cmdb_field_definitions` and seeds locked built-ins
- Built-in **OS Family** / **OS Version** and **Product Type** / **Product Version** are separate native fields (`origin=builtin`, `storage=native`) — never collapsed or deleted
- Custom defs use `origin=custom`, `storage=custom_fields`; values still attach on component `custom_fields`
- APIs: `/api/field-definitions` (all defs) and `/api/custom-fields` facade (custom-only list for Inventory forms)

### Column configurations (Phase 8)

- Collection: `cmdb_column_configurations` (unique `(tenant_id, grid_key)`)
- Grids: `inventory` and `relationships`
- Settings: visibility, order, optional width (px), optional pin (`left` / `right`)
- Locked (always visible, never collapsed): Inventory **OS Family / OS Version / Product Type / Product Version**; Relationships **Protocol / Source Port / Target Port**; plus **Actions**
- APIs: `GET/PUT/DELETE /api/column-configurations/{grid_key}` (+ list)
- Column Settings UI replaces the Phase 2/7 “coming soon” placeholder and drives both grids

### Custom entity tables (0.18.0)

- **Storage:** `cmdb_custom_table_definitions` (schema) + single `cmdb_custom_records` collection partitioned by `table_key` (not one Mongo collection per table)
- Columns: `string` / `number` / `boolean` / `enum` / `reference` — references store `{ref_id, ref_table}` targeting a CMDB type (`Server`…) or another custom `table_key`
- Relationships: optional `source_table` / `target_table` so custom records can HOSTED_ON / DEPENDS_ON / etc. with CMDB CIs or other custom rows; `/api/components*` unchanged
- APIs: `/api/custom-tables*`, `/api/custom-tables/{key}/records*`, `/api/entity-refs`
- UI: Configuration → Custom Tables; Operations sidebar lists defined tables for inventory-like CRUD; Relationships picker includes custom entities
- Core CMDB builtins (OS/product; protocol/ports) are **not** collapsed

### Important: one browser host only

Session cookies are **host-scoped**. `http://localhost:8200` and `http://127.0.0.1:8200` are **different** sites to the browser.

- Set `OIDC_REDIRECT_URI` to one host (example: `http://localhost:8200/auth/callback`)
- Always open the UI on **that same host**
- Mixing hosts causes `Invalid or expired OIDC state` because `/auth/login` sets cookies on one host and the IdP callback hits the other
- If you open the “wrong” host, `/auth/login` now redirects to the `OIDC_REDIRECT_URI` host automatically, and the login page shows a host-mismatch warning

### Keycloak local smoke test

1. Run Keycloak (example with Docker):

```bash
docker run -d --name keycloak -p 8080:8080 \
  -e KEYCLOAK_ADMIN=admin -e KEYCLOAK_ADMIN_PASSWORD=admin \
  quay.io/keycloak/keycloak:25.0 start-dev
```

2. In the Keycloak admin console (`http://localhost:8080`):
   - Create realm `svrmon24`
   - Create client `svrmon24-ui` (confidential), Client authentication **On**
   - Valid redirect URI: `http://localhost:8200/auth/callback`
   - Valid post-logout redirect: `http://localhost:8200/`
   - Create a test user (no special admin role required)

3. Set in `.env`:

```bash
OIDC_ENABLED=true
OIDC_ISSUER=http://localhost:8080/realms/svrmon24
OIDC_CLIENT_ID=svrmon24-ui
OIDC_CLIENT_SECRET=<client-secret-from-keycloak>
OIDC_REDIRECT_URI=http://localhost:8200/auth/callback
BASIC_AUTH_ENABLED=false
SESSION_SECRET=<long-random-string>
```

4. Start the app, open **`http://localhost:8200/`** (not `127.0.0.1` unless your redirect URI also uses it). You should see the dedicated login page (no sidebar). Click **Sign in with SSO (OIDC)**, complete Keycloak login, land on Dashboard, and confirm `/api/me` shows `"auth_method": "oidc"`.

5. Optional coexistence check: set `BASIC_AUTH_ENABLED=true` with known credentials; the Basic form appears alongside SSO. With the flag off, Basic headers must not authenticate.

6. If you previously mixed hosts and hit a state error, clear site cookies for both `localhost` and `127.0.0.1`, then retry on the redirect-URI host only.

Entra ID works the same way with issuer `https://login.microsoftonline.com/<tenant-id>/v2.0` and an app registration redirect URI matching `OIDC_REDIRECT_URI`.

## Tests

```powershell
# Windows
.\.venv\Scripts\python.exe -m pytest -v
```

```bash
# Linux
pytest -v
```

## API overview

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/` | Public UI | Dashboard + CMDB UI |
| GET | `/health` | Public | Liveness |
| GET | `/api/auth/config` | Public | Auth feature flags for the UI |
| GET | `/auth/login` | Public | Start OIDC Authorization Code + PKCE |
| GET | `/auth/callback` | Public | OIDC callback → session cookie |
| GET/POST | `/auth/logout` | Public | Clear session (+ optional IdP logout) |
| GET | `/api/status` | OIDC / Basic* | App + MongoDB status |
| GET | `/api/me` | OIDC / Basic* | Principal (+ tenant/membership when OIDC-linked) |
| GET | `/api/tenants` | OIDC / Basic* | List tenants (migration tenant only) |
| GET | `/api/tenants/current` | OIDC / Basic* | Current / migration tenant |
| GET | `/api/memberships` | OIDC / Basic* | Memberships for current OIDC user |
| GET | `/api/dashboard/summary` | OIDC / Basic* | Live dashboard widgets |
| GET/POST | `/api/components` | OIDC / Basic* | List / create components |
| GET/PUT/DELETE | `/api/components/{id}` | OIDC / Basic* | Get / update / delete |
| GET | `/api/components/{id}/delete-preview` | OIDC / Basic* | Delete confirmation + relationship warning |
| GET/POST | `/api/field-definitions` | OIDC / Basic* | CMDB field definitions (custom + built-in) |
| GET/PUT/DELETE | `/api/field-definitions/{key}` | OIDC / Basic* | Get / update / delete field definition |
| GET/POST | `/api/custom-fields` | OIDC / Basic* | Facade — custom field definitions (compat) |
| GET/PUT/DELETE | `/api/custom-fields/{key}` | OIDC / Basic* | Facade — get / update / delete custom field |
| GET | `/api/column-configurations` | OIDC / Basic* | List Inventory + Relationships column configs |
| GET/PUT/DELETE | `/api/column-configurations/{grid}` | OIDC / Basic* | Get / save / reset grid column configuration |
| GET/POST | `/api/custom-tables` | OIDC / Basic* | List / create custom table definitions |
| GET/PUT/DELETE | `/api/custom-tables/{key}` | OIDC / Basic* | Get / update / delete custom table (+ records on delete) |
| POST/PUT/DELETE | `/api/custom-tables/{key}/columns[/{col}]` | OIDC / Basic* | Add / update / delete columns |
| GET/POST | `/api/custom-tables/{key}/records` | OIDC / Basic* | List / create custom records |
| GET/PUT/DELETE | `/api/custom-tables/{key}/records/{id}` | OIDC / Basic* | Get / update / delete custom record |
| GET | `/api/entity-refs` | OIDC / Basic* | Unified CMDB + custom entity picker |
| GET/POST | `/api/relationships` | OIDC / Basic* | List / create relationships |
| GET/PUT/DELETE | `/api/relationships/{id}` | OIDC / Basic* | Get / update / delete |
| GET | `/api/relationships/types` | OIDC / Basic* | Type meaning + direction docs |
| GET | `/api/dependencies/{id}` | OIDC / Basic* | Upstream + downstream + impact bundle |
| GET | `/api/diagnostics/profiles` | OIDC / Basic* | Approved simulated profiles |
| POST | `/api/diagnostics` | OIDC / Basic* | Start SIMULATED diagnostic |
| GET | `/api/diagnostics` | OIDC / Basic* | Diagnostic history |
| GET | `/api/diagnostics/{id}` | OIDC / Basic* | Diagnostic detail |
| POST | `/api/diagnostics/{id}/analyze` | OIDC / Basic* | Ollama / fallback AI analysis |
| GET | `/api/diagnostics/ollama/status` | OIDC / Basic* | Local Ollama probe |

\*Basic only when `BASIC_AUTH_ENABLED=true`.

### Inventory columns (never combined)

Component ID | Hostname/Component Name | Component Type | **OS Family** | **OS Version** | **Product Type** | **Product Version** | Environment | Status | Actions

### Relationship columns (never combined)

Relationship ID | Source | Target | Type | **Protocol** | **Source Port** | **Target Port** | Environment | Discovery | Verification | Actions

## Safety / limitations

- Diagnostics are **SIMULATED / SYNTHETIC_DEMO** until live probes are explicitly approved in a later phase.
- No remote shell, SQL, or network scanning from this application.
- AI analysis never auto-executes remediation and must not invent telemetry.
- Impact results list **potentially affected** applications only — not confirmed outages.
- Default Basic auth is **disabled**; placeholders (`change-me`) must be replaced if the flag is enabled for shared use.
- Shared-DB hard tenant isolation is **on** (`isolation_enforced=true`). UX remains single logical org (**SVRMON24 Legacy**); org switcher is still disabled.

## Project layout

```
svrmon24/
  app/                 # FastAPI application
    diagnostics/       # Simulated profiles + generator
    models/            # Pydantic models (incl. tenants)
    routers/           # HTTP routers (OIDC + tenants/memberships)
    services/          # Business logic (CMDB, deps, AI, tenancy)
    static/            # Dashboard UI (HTML/CSS/JS)
    auth.py            # Unified OIDC session + Basic flag
    oidc.py            # Discovery / PKCE / token validation
    tenancy.py         # Migration tenant constants + scoping helpers
    tenant_context.py  # Resolve current tenant from membership / Basic
  scripts/             # Demo seed, tenant backfill, platform-admin CLI
  tests/               # Pytest suite (incl. cross-tenant denial)
  requirements.txt
  .env.example         # Placeholders only
  README.md
  pytest.ini
```

## License / ownership

Internal project repository: `gpradeep4/svrmon24`.
