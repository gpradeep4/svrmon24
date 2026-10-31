"""Idempotent demo seed script tests (uses test MongoDB via conftest)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _load_seed_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "seed_sample_data.py"
    spec = importlib.util.spec_from_file_location("seed_sample_data", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_sample_data_idempotent(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    # ensure Mongo available (clean_db skips otherwise)
    seed = _load_seed_module()
    wiped = seed.wipe_demo()
    assert wiped["components"] == 0

    first = seed.seed()
    assert first["created"] >= 15
    assert first["skipped"] == 0

    second = seed.seed()
    assert second["created"] == 0
    assert second["skipped"] >= 15

    comps = client.get("/api/components?q=demo-&page_size=50", headers=auth_headers)
    assert comps.status_code == 200
    assert comps.json()["total"] >= 9

    # separate OS / product columns present on inventory rows
    inv = comps.json()["inventory"]
    server = next(r for r in inv if r["component_id"] == "demo-srv-web01")
    assert server["os_family"] == "RHEL"
    assert server["os_version"] == "9.4"
    mw = next(r for r in inv if r["component_id"] == "demo-mware-wls")
    assert mw["product_type"] == "WebLogic"
    assert mw["product_version"] == "14.1.1"

    rels = client.get("/api/relationships?q=demo-&page_size=50", headers=auth_headers)
    assert rels.status_code == 200
    assert rels.json()["total"] >= 8
    billing_db = next(
        r for r in rels.json()["rows"] if r["relationship_id"] == "demo-rel-billing-db"
    )
    assert billing_db["protocol"] == "TCP"
    assert billing_db["source_port"] == "45000"
    assert billing_db["target_port"] == "1521"

    diags = client.get(
        "/api/diagnostics?component_id=demo-srv-web01", headers=auth_headers
    )
    assert diags.status_code == 200
    assert diags.json()["total"] >= 1
    assert diags.json()["items"][0]["execution_mode"] == "SIMULATED"

    # wipe only demo data
    after = seed.wipe_demo()
    assert after["components"] >= 9
    assert after["relationships"] >= 8
    empty = client.get("/api/components?q=demo-", headers=auth_headers)
    assert empty.json()["total"] == 0
