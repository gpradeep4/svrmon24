# SVRMON24

AI-assisted infrastructure CMDB, dependency mapping, **SIMULATED** diagnostics, local Ollama analysis, and operations dashboard.

Stack: **FastAPI + Uvicorn + MongoDB (PyMongo) + HTTP Basic auth**. Diagnostics never contact remote hosts and never execute shell/SQL/network scans.

## Features (Phases 2–8)

| Area | Capability |
| --- | --- |
| Auth / ops | HTTP Basic, `/health`, `/api/status`, structured logging |
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
- Optional: local [Ollama](https://ollama.com/) for AI analysis (`llama3.2:3b` or another configured model)

## Quick start — Windows PowerShell

```powershell
cd C:\path\to\svrmon24
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env — set BASIC_AUTH_USERNAME / BASIC_AUTH_PASSWORD and MONGODB_URI
python -m app.main
```

Or with Uvicorn:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8200
```

Open `http://localhost:8200/` → enter Basic auth credentials → use Dashboard / Inventory / Relationships / Dependencies / Diagnostics.

## Quick start — RHEL / Linux bash

```bash
cd /path/to/svrmon24
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set BASIC_AUTH_USERNAME / BASIC_AUTH_PASSWORD and MONGODB_URI
python -m app.main
```

Or:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8200
```

## Configuration

Copy `.env.example` → `.env` (never commit `.env`). Placeholders only in the example file:

| Variable | Purpose |
| --- | --- |
| `BASIC_AUTH_USERNAME` / `BASIC_AUTH_PASSWORD` | HTTP Basic credentials |
| `MONGODB_URI` / `MONGODB_DB` | MongoDB connection |
| `APP_HOST` / `APP_PORT` | Bind address (default `0.0.0.0:8200`) |
| `OLLAMA_URL` / `OLLAMA_MODEL` / `OLLAMA_TIMEOUT_SECONDS` | Local Ollama for AI analysis |

When Ollama is unavailable, diagnostic analysis uses a deterministic rule-based fallback. Analysis derived from simulated diagnostics is clearly labeled.

## Auth

- Public: `/`, `/health`, `/static/*`
- Protected: `/api/*` (HTTP Basic)
- Longer-term auth is expected to move to OIDC

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
| GET | `/api/status` | Basic | App + MongoDB status |
| GET | `/api/me` | Basic | Auth smoke check |
| GET | `/api/dashboard/summary` | Basic | Live dashboard widgets |
| GET/POST | `/api/components` | Basic | List / create components |
| GET/PUT/DELETE | `/api/components/{id}` | Basic | Get / update / delete |
| GET | `/api/components/{id}/delete-preview` | Basic | Delete confirmation + relationship warning |
| GET/POST | `/api/custom-fields` | Basic | Custom field definitions |
| GET/POST | `/api/relationships` | Basic | List / create relationships |
| GET/PUT/DELETE | `/api/relationships/{id}` | Basic | Get / update / delete |
| GET | `/api/relationships/types` | Basic | Type meaning + direction docs |
| GET | `/api/dependencies/{id}` | Basic | Upstream + downstream + impact bundle |
| GET | `/api/diagnostics/profiles` | Basic | Approved simulated profiles |
| POST | `/api/diagnostics` | Basic | Start SIMULATED diagnostic |
| GET | `/api/diagnostics` | Basic | Diagnostic history |
| GET | `/api/diagnostics/{id}` | Basic | Diagnostic detail |
| POST | `/api/diagnostics/{id}/analyze` | Basic | Ollama / fallback AI analysis |
| GET | `/api/diagnostics/ollama/status` | Basic | Local Ollama probe |

### Inventory columns (never combined)

Component ID | Hostname/Component Name | Component Type | **OS Family** | **OS Version** | **Product Type** | **Product Version** | Environment | Status | Actions

### Relationship columns (never combined)

Relationship ID | Source | Target | Type | **Protocol** | **Source Port** | **Target Port** | Environment | Discovery | Verification | Actions

## Safety / limitations

- Diagnostics are **SIMULATED / SYNTHETIC_DEMO** until live probes are explicitly approved in a later phase.
- No remote shell, SQL, or network scanning from this application.
- AI analysis never auto-executes remediation and must not invent telemetry.
- Impact results list **potentially affected** applications only — not confirmed outages.
- Default Basic auth placeholders (`change-me`) must be replaced before any shared deployment.

## Project layout

```
svrmon24/
  app/                 # FastAPI application
    diagnostics/       # Simulated profiles + generator
    models/            # Pydantic models
    routers/           # HTTP routers
    services/          # Business logic (CMDB, deps, AI, dashboard)
    static/            # Dashboard UI (HTML/CSS/JS)
  tests/               # Pytest suite
  requirements.txt
  .env.example         # Placeholders only
  README.md
  pytest.ini
```

## License / ownership

Internal project repository: `gpradeep4/svrmon24`.
