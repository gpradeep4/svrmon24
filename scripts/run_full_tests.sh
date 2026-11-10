#!/usr/bin/env bash
# Run the full SVRMON24 pytest suite (same as CI / make test).
set -euo pipefail
cd "$(dirname "$0")/.."
export APP_ENV="${APP_ENV:-test}"
export MONGODB_URI="${MONGODB_URI:-mongodb://localhost:27017}"
export MONGODB_DB="${MONGODB_DB:-svrmon24_test}"
exec python -m pytest -v "$@"
