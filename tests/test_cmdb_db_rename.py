"""CMDB database rename/cutover (slice 2K / 0.42.0) — config + light smoke."""

from __future__ import annotations

from app import __version__
from app.config import Settings, get_settings
from app.db import get_database, get_itsm_database, ping_database, reset_client_for_tests
from fastapi.testclient import TestClient


def test_version_bump_for_cmdb_db_rename() -> None:
    assert __version__ == "0.77.0"


def test_cmdb_default_database_is_svrmon_cmdb(monkeypatch) -> None:
    """With no CMDB env overrides, resolved CMDB DB is ``svrmon-cmdb``."""
    monkeypatch.delenv("MONGODB_DB", raising=False)
    monkeypatch.delenv("MONGODB_CMDB_DB", raising=False)
    monkeypatch.delenv("MONGODB_ITSM_DB", raising=False)
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert settings.mongodb_db == "svrmon-cmdb"
    assert settings.cmdb_database_name == "svrmon-cmdb"
    assert settings.itsm_database_name == "svrmon-itsm"
    get_settings.cache_clear()


def test_cmdb_alias_override_and_itsm_isolation(monkeypatch) -> None:
    """``MONGODB_CMDB_DB`` wins over ``MONGODB_DB``; ITSM stays on its own name."""
    monkeypatch.setenv("MONGODB_DB", "should-not-win")
    monkeypatch.setenv("MONGODB_CMDB_DB", "svrmon-cmdb")
    monkeypatch.setenv("MONGODB_ITSM_DB", "svrmon-itsm")
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert settings.cmdb_database_name == "svrmon-cmdb"
    assert settings.itsm_database_name == "svrmon-itsm"
    assert settings.cmdb_database_name != settings.itsm_database_name
    get_settings.cache_clear()


def test_precutover_name_still_honored_via_mongodb_db(monkeypatch) -> None:
    """Ops can keep reading ``svrmon24`` until data is copied/renamed."""
    monkeypatch.delenv("MONGODB_CMDB_DB", raising=False)
    monkeypatch.setenv("MONGODB_DB", "svrmon24")
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert settings.cmdb_database_name == "svrmon24"
    get_settings.cache_clear()


def test_blank_mongodb_cmdb_db_falls_through_to_mongodb_db(monkeypatch) -> None:
    """Whitespace / empty ``MONGODB_CMDB_DB`` must not override ``MONGODB_DB``."""
    monkeypatch.setenv("MONGODB_DB", "svrmon24")
    monkeypatch.setenv("MONGODB_CMDB_DB", "   ")
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert settings.cmdb_database_name == "svrmon24"
    get_settings.cache_clear()


def test_get_database_uses_resolved_cmdb_name(monkeypatch) -> None:
    """``get_database()`` opens the resolved CMDB name, not a hard-coded string."""
    monkeypatch.setenv("MONGODB_DB", "legacy-ignored")
    monkeypatch.setenv("MONGODB_CMDB_DB", "explicit-cmdb-handle")
    monkeypatch.setenv("MONGODB_ITSM_DB", "explicit-itsm-handle")
    get_settings.cache_clear()
    reset_client_for_tests()
    settings = Settings(_env_file=None)
    assert get_database(settings).name == "explicit-cmdb-handle"
    assert get_itsm_database(settings).name == "explicit-itsm-handle"
    reset_client_for_tests()
    get_settings.cache_clear()


def test_ping_reports_dual_databases(monkeypatch) -> None:
    monkeypatch.setenv("MONGODB_DB", "svrmon-cmdb-ping-probe")
    monkeypatch.delenv("MONGODB_CMDB_DB", raising=False)
    monkeypatch.setenv("MONGODB_ITSM_DB", "svrmon-itsm-ping-probe")
    get_settings.cache_clear()
    reset_client_for_tests()
    settings = Settings(_env_file=None)
    status = ping_database(settings)
    assert status["database"] == "svrmon-cmdb-ping-probe"
    assert status["cmdb_database"] == "svrmon-cmdb-ping-probe"
    assert status["itsm_database"] == "svrmon-itsm-ping-probe"
    reset_client_for_tests()
    get_settings.cache_clear()


def test_cmdb_smoke_reads_writes_configured_database(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    """Light CMDB API smoke: create + list land in the resolved CMDB DB handle."""
    # Keep suite isolation DBs from conftest; assert handle separation + write path.
    cmdb = get_database()
    itsm = get_itsm_database()
    assert cmdb.name != itsm.name
    assert "itsm" in itsm.name or itsm.name == "svrmon-itsm"

    created = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Server",
            "name": "cmdb-rename-smoke",
            "hostname": "cmdb-rename-smoke.example",
            "environment": "lab",
            "status": "active",
            "os_family": "linux",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    component_id = body["component_id"]

    listed = client.get("/api/components", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    ids = {row["component_id"] for row in listed.json()["items"]}
    assert component_id in ids

    # Document lives on CMDB handle, not ITSM.
    assert cmdb["cmdb_servers"].find_one({"component_id": component_id}) is not None
    assert itsm["cmdb_servers"].find_one({"component_id": component_id}) is None


def test_api_status_exposes_cmdb_and_itsm_names(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/status", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    mongo = payload.get("mongodb") or {}
    assert "cmdb_database" in mongo
    assert "itsm_database" in mongo
    assert mongo["cmdb_database"] != mongo["itsm_database"]
    assert payload.get("version") == "0.77.0"
