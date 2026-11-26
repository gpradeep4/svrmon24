#!/usr/bin/env bash
# Start SVRMON24 API monolith (RHEL / Linux).
# Prefer: cp .env.example .env  →  edit secrets  →  ./scripts/run_api.sh
# Health: curl -sf http://127.0.0.1:${APP_PORT:-8200}/health
# Live masters stay fail-closed until env + Configuration → Live / Runtime.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .venv/bin/activate ]]; then
  echo "Missing .venv. Create it with: python3 -m venv .venv" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Warning: no .env found. Copy .env.example → .env before production use." >&2
fi

# shellcheck disable=SC1091
source .venv/bin/activate
exec python -m app.main
