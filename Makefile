.PHONY: test test-full compile test-phase14

# Release / CI gate: entire suite under tests/ (matches .github/workflows/ci.yml).
test test-full:
	python -m pytest -v

# Phase-style targeted runs (local iteration only — not a substitute for `make test`).
test-phase14:
	python -m pytest tests/test_phase14_audit_security.py -q

compile:
	python -m compileall -q app
