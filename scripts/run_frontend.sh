#!/usr/bin/env bash
# Serve SVRMON24 UI via Docker Compose (nginx proxy to API on :8200).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec docker compose up frontend "$@"