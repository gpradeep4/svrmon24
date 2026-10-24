"""Custom field definition API and validation tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_custom_field_crud_and_required_validation(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post(
        "/api/custom-fields",
        headers=auth_headers,
        json={
            "field_key": "cost_center",
            "label": "Cost Center",
            "field_type": "string",
            "applies_to": ["Server"],
            "required": True,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["field_key"] == "cost_center"

    listed = client.get("/api/custom-fields?component_type=Server", headers=auth_headers)
    assert listed.status_code == 200
    assert any(i["field_key"] == "cost_center" for i in listed.json()["items"])

    # Missing required custom field → 422
    missing = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Server",
            "name": "web",
            "environment": "prod",
            "hostname": "web",
            "os_family": "RHEL",
            "os_version": "9",
        },
    )
    assert missing.status_code == 422

    ok = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Server",
            "name": "web",
            "environment": "prod",
            "hostname": "web",
            "os_family": "RHEL",
            "os_version": "9",
            "custom_fields": {"cost_center": "IT-OPS"},
        },
    )
    assert ok.status_code == 201
    assert ok.json()["custom_fields"]["cost_center"] == "IT-OPS"

    deleted = client.delete("/api/custom-fields/cost_center", headers=auth_headers)
    assert deleted.status_code == 200


def test_custom_field_enum_validation(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    bad = client.post(
        "/api/custom-fields",
        headers=auth_headers,
        json={
            "field_key": "tier",
            "label": "Tier",
            "field_type": "enum",
            "applies_to": ["*"],
            "enum_values": [],
        },
    )
    assert bad.status_code == 422

    created = client.post(
        "/api/custom-fields",
        headers=auth_headers,
        json={
            "field_key": "tier",
            "label": "Tier",
            "field_type": "enum",
            "applies_to": ["*"],
            "enum_values": ["gold", "silver"],
        },
    )
    assert created.status_code == 201

    invalid = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Application",
            "name": "portal",
            "environment": "prod",
            "application_name": "portal",
            "custom_fields": {"tier": "bronze"},
        },
    )
    assert invalid.status_code == 422
