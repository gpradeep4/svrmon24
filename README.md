# SVRMON24

AI-powered infrastructure monitoring, CMDB, dependency mapping, and diagnostics.

**Phase 2** foundation: FastAPI + Uvicorn, MongoDB via PyMongo, HTTP Basic auth, structured logging, and tests.

**Phase 3** adds the CMDB component inventory (Server / Network / Middleware / Database / Application) with CRUD API, search/filter/pagination, custom-field definitions, delete confirmation with relationship warning hook, and a browser UI at `/`.

Diagnostics remain simulated — no real remote execution.

## Requirements

- Python 3.11+ (verified on Windows; compatible with RHEL Linux)
- MongoDB reachable via `MONGODB_URI` (app starts even if MongoDB is temporarily down)

## Quick start (PowerShell / Windows)

```powershell
cd C:\Users\Pradeep\Projects\svrmon24
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env: set BASIC_AUTH_USERNAME / BASIC_AUTH_PASSWORD and MONGODB_URI
python -m app.main
```

Or with Uvicorn directly:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8200
```

Open the UI at `http://localhost:8200/` and connect with Basic auth credentials.

## Quick start (RHEL / Linux bash)

```bash
cd /path/to/svrmon24
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
python -m app.main
```

## Auth

Phase 2+ uses **HTTP Basic** credentials from `BASIC_AUTH_USERNAME` and `BASIC_AUTH_PASSWORD`.
`/health` and the UI shell are public; API routes require authentication. Longer-term auth will move to OIDC.

## Tests

```powershell
pytest
```

## Endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/` | Public UI | CMDB inventory UI |
| GET | `/health` | Public | Liveness |
| GET | `/api/status` | Basic | App + MongoDB status |
| GET | `/api/me` | Basic | Auth smoke check |
| GET/POST | `/api/components` | Basic | List / create components |
| GET/PUT/DELETE | `/api/components/{id}` | Basic | Get / update / delete |
| GET | `/api/components/{id}/delete-preview` | Basic | Delete confirmation + relationship warning |
| GET/POST | `/api/custom-fields` | Basic | Custom field definitions |

### Inventory columns (never combined)

Component ID | Hostname/Component Name | Component Type | OS Family | OS Version | Product Type | Product Version | Environment | Status | Actions

N/A values render as an em dash.
