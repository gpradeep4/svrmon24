# SVRMON24

AI-powered infrastructure monitoring, CMDB, dependency mapping, and diagnostics.

**Phase 2** delivers the application foundation: FastAPI + Uvicorn, MongoDB via PyMongo, HTTP Basic auth from environment variables, structured logging, centralized exception handling, and automated tests. Diagnostics remain simulated â€” no real remote execution.

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
# Edit .env â€” set BASIC_AUTH_USERNAME / BASIC_AUTH_PASSWORD and MONGODB_URI
python -m app.main
```

Or with Uvicorn directly:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8200
```

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

Phase 2 uses **HTTP Basic** credentials from `BASIC_AUTH_USERNAME` and `BASIC_AUTH_PASSWORD`.
`/health` is public; other API routes require authentication. Longer-term auth will move to OIDC.

## Tests

```powershell
pytest
```

## Endpoints (Phase 2)

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/health` | Public | Liveness |
| GET | `/api/status` | Basic | App + MongoDB status |
| GET | `/api/me` | Basic | Auth smoke check |

