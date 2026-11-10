# CI full release gate

SVRMON24 uses **two testing postures**:

| Context | What to run | Purpose |
| --- | --- | --- |
| Phase / feature work | Targeted files or directories (e.g. `pytest tests/test_phase14_audit_security.py -q`) | Fast feedback while building a phase |
| **Release / CI** | **Full suite** — all tests under `tests/` | Merge and deploy gate |

GitHub Actions workflow [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on every **pull request** and **push to `main`**. It:

1. Starts **MongoDB** (service container) — required for CMDB integration tests.
2. Installs dependencies from `requirements.txt`.
3. Byte-compiles `app/` (`python -m compileall`) as a lightweight syntax check (no separate linter/typechecker is configured yet).
4. Runs **`python -m pytest -v`** with no path filters — the complete suite (~189 tests).

CI is green only when the full suite passes. Skipping or narrowing tests in CI is not supported.

## Run the full suite locally

MongoDB must be reachable at `mongodb://localhost:27017` (or set `MONGODB_URI` / `MONGODB_DB`).

```bash
make test
# or
./scripts/run_full_tests.sh
# or
python -m pytest -v
```

Targeted phase commands remain valid for local iteration; run `make test` before opening a PR.

## Related

- [`docs/release-hardening.md`](release-hardening.md) — production checklist (includes targeted Phase 14 commands for operators)
- Root [`README.md`](../README.md) — Tests section
