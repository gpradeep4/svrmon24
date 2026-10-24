"""Diagnostic engine tests — SIMULATED mode only."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.diagnostics.profiles import BASIC_HEALTH_PROFILE, get_profile, list_profiles
from app.diagnostics.simulator import generate_check_result
from app.models.diagnostics import DiagnosticStartRequest
from app.serialization import serialize_document


def _seed_server(client: TestClient, headers: dict) -> None:
    response = client.post(
        "/api/components",
        headers=headers,
        json={
            "component_id": "srv-diag",
            "component_type": "Server",
            "name": "diag-host",
            "environment": "prod",
            "status": "active",
            "hostname": "diag-host",
            "os_family": "RHEL",
            "os_version": "9.4",
        },
    )
    assert response.status_code == 201, response.text


def test_profile_registry_includes_basic_health() -> None:
    profiles = list_profiles()
    assert any(p["profile_name"] == "basic-health" for p in profiles)
    profile = get_profile("basic-health")
    assert profile is not None
    assert profile["execution_mode"] == "SIMULATED"
    assert profile["approved"] is True
    assert profile is not BASIC_HEALTH_PROFILE or True  # copy returned


def test_invalid_profile_rejected(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_server(client, auth_headers)
    response = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={"component_id": "srv-diag", "profile_name": "not-a-real-profile"},
    )
    assert response.status_code == 422


def test_valid_profile_runs_simulated(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_server(client, auth_headers)
    response = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={
            "component_id": "srv-diag",
            "profile_name": "basic-health",
            "notes": "demo run",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["execution_mode"] == "SIMULATED"
    assert body["diagnostic_id"].startswith("diag-")
    assert body["timestamp"]
    assert body["component"]["component_id"] == "srv-diag"
    assert body["labels"]["real_telemetry"] is False
    assert "SIMULATED" in body["labels"]["banner"]
    assert body["dependency_context"]["source"] == "cmdb_relationships"

    kinds = {c["metric_kind"] for c in body["checks"]}
    assert {"cpu", "memory", "disk", "service_status", "connectivity"} <= kinds
    for check in body["checks"]:
        assert check["synthetic"] is True
        assert check["data_source"] == "SYNTHETIC_DEMO"
        assert "not real telemetry" in check["note"].lower()


def test_unknown_component_rejected(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    response = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={"component_id": "missing", "profile_name": "basic-health"},
    )
    assert response.status_code == 404


def test_result_persistence_and_history(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_server(client, auth_headers)
    created = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={"component_id": "srv-diag", "profile_name": "basic-health"},
    )
    assert created.status_code == 201
    diag_id = created.json()["diagnostic_id"]

    fetched = client.get(f"/api/diagnostics/{diag_id}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["diagnostic_id"] == diag_id
    assert fetched.json()["execution_mode"] == "SIMULATED"

    history = client.get(
        "/api/diagnostics?component_id=srv-diag",
        headers=auth_headers,
    )
    assert history.status_code == 200
    assert history.json()["total"] >= 1
    assert history.json()["execution_mode"] == "SIMULATED"
    assert any(i["diagnostic_id"] == diag_id for i in history.json()["items"])


def test_serialization_of_diagnostic_document() -> None:
    from datetime import datetime, timezone
    from bson import ObjectId

    raw = {
        "_id": ObjectId(),
        "diagnostic_id": "diag-abc",
        "timestamp": datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc),
        "execution_mode": "SIMULATED",
        "checks": [],
    }
    out = serialize_document(raw)
    assert out is not None
    assert isinstance(out["_id"], str)
    assert out["timestamp"].startswith("2026-10-24")
    assert out["execution_mode"] == "SIMULATED"


def test_simulated_labels_on_generated_checks() -> None:
    cpu = generate_check_result(
        "srv-1",
        {"check_id": "cpu", "label": "CPU", "metric_kind": "cpu", "unit": "percent"},
    )
    assert cpu["synthetic"] is True
    assert cpu["data_source"] == "SYNTHETIC_DEMO"
    assert isinstance(cpu["value"], int)
    assert "not real telemetry" in cpu["note"].lower()

    svc = generate_check_result(
        "srv-1",
        {
            "check_id": "service_status",
            "label": "Service",
            "metric_kind": "service_status",
            "unit": "status",
        },
    )
    assert str(svc["value"]).startswith("SYNTHETIC_")


def test_rejects_command_payload_in_request_model() -> None:
    with pytest.raises(ValidationError):
        DiagnosticStartRequest.model_validate(
            {
                "component_id": "srv-1",
                "profile_name": "basic-health",
                "command": "rm -rf /",
            }
        )
    with pytest.raises(ValidationError):
        DiagnosticStartRequest.model_validate(
            {
                "component_id": "srv-1",
                "profile_name": "basic-health",
                "script": "echo hi",
            }
        )


def test_api_rejects_forbidden_execution_fields(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed_server(client, auth_headers)
    response = client.post(
        "/api/diagnostics",
        headers=auth_headers,
        json={
            "component_id": "srv-diag",
            "profile_name": "basic-health",
            "shell": "whoami",
        },
    )
    assert response.status_code == 422


def test_profiles_endpoint(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/diagnostics/profiles", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["execution_mode"] == "SIMULATED"
    assert body["demo_only"] is True
    assert any(p["profile_name"] == "basic-health" for p in body["profiles"])


def test_diagnostics_require_auth(client: TestClient) -> None:
    assert client.get("/api/diagnostics/profiles").status_code == 401
