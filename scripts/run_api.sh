#!/usr/bin/env bash
# Start SVRMON24 API (RHEL / Linux)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .venv/bin/activate ]]; then
  echo "Missing .venv. Create it with: python3 -m venv .venv" >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
exec python -m app.main
