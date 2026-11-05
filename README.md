# SVRMON24

AI-assisted infrastructure CMDB, dependency mapping, **SIMULATED** diagnostics, local Ollama analysis, and operations dashboard.

Stack: **FastAPI + Uvicorn + MongoDB (PyMongo) + provider-neutral OIDC** (HTTP Basic optional via feature flag). Diagnostics never contact remote hosts and never execute shell/SQL/network scans.

## Features (through Master Phase 4)

| Area | Capability |
| --- | --- |
| Auth / ops | OIDC (Auth Code + PKCE), feature-flagged HTTP Basic, `/health`, `/api/status`, structured logging |
| Tenancy | `tenants` / `users` / `memberships`; migration tenant **SVRMON24 Legacy** (`tenant-svrmon24-legacy`); dual-write `tenant_id` on new CMDB docs — **no hard isolation yet** |
| CMDB | Server / Network / Middleware / Database / Application inventory |
| Custom fields | Per-type (or global) field definitions |
| Relationships | HOSTED_ON / DEPENDS_ON / CONNECTS_TO / ROUTES_TO |
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
- **Basic auth is disabled by default** for production-oriented deployments. Enable only for migration/testing. It must **not** bypass future tenant authorization once multi-tenant isolation lands.
- OIDC login links a local user + **member** membership on the migration tenant — **never** auto-admin the first public registrant
- Platform admin is **CLI/operator bootstrap only**: `python scripts/bootstrap_platform_admin.py --username operator --email ops@example.com`

### Tenancy (Phase 4)

- Startup (and `python scripts/ensure_migration_tenant.py`) idempotently seeds `tenant-svrmon24-legacy` / **SVRMON24 Legacy**
- New writes to `components`, `custom_field_definitions`, `cmdb_relationships`, and `diagnostic_history` dual-write `tenant_id` (migration tenant). Existing rows may still have null `tenant_id` until Phase 5 backfill
- `component_id` remains **globally** unique
- APIs: `GET /api/tenants`, `GET /api/tenants/current`, `GET /api/tenants/{id}`, `GET /api/memberships` — org switcher is **not** activated; `isolation_enforced=false`
- `/api/me` includes `current_tenant_id` + `current_tenant_display_name` for the header banner
- Hard cross-tenant denial is **Master Phase 5** (not this release)

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
| GET/POST | `/api/custom-fields` | OIDC / Basic* | Custom field definitions |
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
- Single logical tenant (**SVRMON24 Legacy**) — tenant models exist; **no** hard isolation or org switcher activation yet (Phase 5).

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
    tenancy.py         # Migration tenant constants + dual-write helper
  scripts/             # Demo seed, migration tenant ensure, platform-admin CLI
  tests/               # Pytest suite
  requirements.txt
  .env.example         # Placeholders only
  README.md
  pytest.ini
```

## License / ownership

Internal project repository: `gpradeep4/svrmon24`.
