"""CMDB C0 — asset console–style CI header / Specs / General schema (0.99.10).

Schema-only: native optional fields, Server Specs, enums, indexes, example
org custom field defs. No CI detail UI.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import __version__
from app.cmdb.models.components import (
    COMMON_OPTIONAL_KEYS,
    ComponentCreate,
    ComponentStatus,
    ComponentType,
    ComponentUpdate,
    ImpactLevel,
    PriorityLevel,
    SupportedFlag,
    UrgencyLevel,
    apply_component_update,
    build_component_document,
)
from app.cmdb.models.custom_fields import example_org_custom_field_specs
from app.cmdb.services.cmdb_collections import COLLECTION_SERVERS, ensure_typed_cmdb_indexes
from app.cmdb.services import custom_fields as custom_fields_service


def test_c0_version_bump() -> None:
    assert __version__ == "0.99.10"


def test_status_enum_map_only_unchanged() -> None:
    assert {s.value for s in ComponentStatus} == {
        "active",
        "inactive",
        "decommissioned",
        "unknown",
    }


def test_example_org_custom_field_specs_are_generic() -> None:
    specs = example_org_custom_field_specs()
    keys = {s["field_key"] for s in specs}
    assert "app_code" in keys
    assert "device_stage" in keys
    assert "supported_countries" in keys
    assert "hostname_alias" in keys
    # Never product-brand org prefixes into schema examples as required natives
    for key in keys:
        assert not key.upper().startswith("UOB_")
        assert "uob" not in key.lower()


def test_server_create_model_accepts_ci_header_and_specs() -> None:
    payload = ComponentCreate(
        component_type=ComponentType.SERVER,
        name="lxiretsgv98.sg.example.com",
        environment="Development",
        description="lxiretsgv98",
        tag_number="TAG-100",
        serial_number="BIOS-UUID-001",
        part_number="PN-9",
        supported=SupportedFlag.YES,
        inventory_name="inv-lxiretsgv98",
        company="ORGA",
        system_role="Application Server",
        status_reason="Deployed",
        impact=ImpactLevel.THREE,
        urgency=UrgencyLevel.THREE,
        priority=PriorityLevel.FIVE,
        users_affected=0,
        additional_information="sample note",
        manufacturer="ExampleCorp",
        model="X86-based PC",
        product_categorization={"tier1": "Hardware", "tier2": "Server", "tier3": "x86"},
        lifecycle={
            "installed_at": datetime(2024, 1, 15, tzinfo=timezone.utc),
        },
        hostname="lxiretsgv98.sg.example.com",
        ip_address="10.1.2.3",
        os_family="Linux",
        os_version="8.9",
        system_type="X86-based PC",
        virtual_system_type="KVM",
        is_virtual=True,
        impact_computation_model="Standard",
        reset_capability="Yes",
        dns_hostname="lxiretsgv98.sg.example.com",
        domain="sg.example.com",
        workgroup=None,
        total_physical_memory_mb=65536,
        flash_memory_mb=0,
    )
    doc = build_component_document(payload, component_id="srv-c0-1", now=datetime.now(timezone.utc))
    assert doc["description"] == "lxiretsgv98"
    assert doc["company"] == "ORGA"
    assert doc["priority"] == "5"
    assert doc["supported"] == "yes"
    assert doc["product_categorization"]["tier1"] == "Hardware"
    assert doc["lifecycle"]["installed_at"] is not None
    assert doc["system_type"] == "X86-based PC"
    assert doc["is_virtual"] is True
    assert doc["total_physical_memory_mb"] == 65536
    for key in COMMON_OPTIONAL_KEYS:
        assert key in doc


def test_non_server_rejects_server_specs() -> None:
    with pytest.raises(ValidationError) as exc:
        ComponentCreate(
            component_type=ComponentType.APPLICATION,
            name="portal",
            environment="prod",
            application_name="portal",
            system_type="X86-based PC",
        )
    assert "system_type" in str(exc.value)


def test_application_accepts_shared_header_fields() -> None:
    payload = ComponentCreate(
        component_type=ComponentType.APPLICATION,
        name="portal",
        environment="prod",
        application_name="portal",
        description="Portal app",
        company="ORGA",
        priority=PriorityLevel.TWO,
        manufacturer="Vendor",
    )
    doc = build_component_document(
        payload, component_id="app-c0-1", now=datetime.now(timezone.utc)
    )
    assert doc["description"] == "Portal app"
    assert doc["company"] == "ORGA"
    assert doc["priority"] == "2"
    assert doc["system_type"] is None


def test_apply_update_round_trips_common_and_server_fields() -> None:
    existing = build_component_document(
        ComponentCreate(
            component_type=ComponentType.SERVER,
            name="web-01",
            environment="prod",
            hostname="web-01",
        ),
        component_id="srv-upd-1",
        now=datetime.now(timezone.utc),
    )
    updated = apply_component_update(
        existing,
        ComponentUpdate(
            serial_number="SN-99",
            priority=PriorityLevel.ONE,
            dns_hostname="web-01.example.com",
            total_physical_memory_mb=8192,
            product_categorization={"tier1": "Compute"},
        ),
        now=datetime.now(timezone.utc),
    )
    assert updated["serial_number"] == "SN-99"
    assert updated["priority"] == "1"
    assert updated["dns_hostname"] == "web-01.example.com"
    assert updated["total_physical_memory_mb"] == 8192
    assert updated["product_categorization"]["tier1"] == "Compute"


def _server_payload(**overrides):
    base = {
        "component_id": "srv-c0-ci",
        "component_type": "Server",
        "name": "c0-ci.example.com",
        "environment": "Development",
        "status": "active",
        "description": "c0-ci",
        "serial_number": "SN-C0-001",
        "company": "ORGA",
        "supported": "yes",
        "impact": "3",
        "urgency": "3",
        "priority": "5",
        "users_affected": 12,
        "manufacturer": "ExampleCorp",
        "model": "Blade",
        "product_categorization": {
            "tier1": "Hardware",
            "tier2": "Server",
            "tier3": "Blade",
        },
        "lifecycle": {"installed_at": "2024-06-01T00:00:00Z"},
        "hostname": "c0-ci.example.com",
        "ip_address": "10.9.8.7",
        "os_family": "RHEL",
        "os_version": "9.4",
        "system_type": "X86-based PC",
        "virtual_system_type": "KVM",
        "is_virtual": True,
        "dns_hostname": "c0-ci.example.com",
        "domain": "example.com",
        "total_physical_memory_mb": 32768,
        "flash_memory_mb": 0,
        "custom_fields": {"app_code": "IRE", "device_stage": "commissioned"},
    }
    base.update(overrides)
    return base


def test_api_server_create_get_update_ci_fields(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    # Seed example org customs so values are documented/available
    custom_fields_service.ensure_example_org_custom_fields(
        tenant_id="tenant-svrmon24-legacy"
    )

    created = client.post(
        "/api/components", headers=auth_headers, json=_server_payload()
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["component_id"] == "srv-c0-ci"
    assert body["description"] == "c0-ci"
    assert body["serial_number"] == "SN-C0-001"
    assert body["company"] == "ORGA"
    assert body["priority"] == "5"
    assert body["supported"] == "yes"
    assert body["system_type"] == "X86-based PC"
    assert body["is_virtual"] is True
    assert body["total_physical_memory_mb"] == 32768
    assert body["product_categorization"]["tier2"] == "Server"
    assert body["custom_fields"]["app_code"] == "IRE"

    fetched = client.get("/api/components/srv-c0-ci", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["dns_hostname"] == "c0-ci.example.com"
    assert fetched.json()["lifecycle"]["installed_at"] is not None

    updated = client.put(
        "/api/components/srv-c0-ci",
        headers=auth_headers,
        json={
            "status_reason": "Deployed",
            "priority": "1",
            "workgroup": "WG1",
            "flash_memory_mb": 512,
            "additional_information": "updated note",
        },
    )
    assert updated.status_code == 200, updated.text
    ubody = updated.json()
    assert ubody["status_reason"] == "Deployed"
    assert ubody["priority"] == "1"
    assert ubody["workgroup"] == "WG1"
    assert ubody["flash_memory_mb"] == 512
    assert ubody["additional_information"] == "updated note"
    # unchanged fields persist
    assert ubody["serial_number"] == "SN-C0-001"
    assert ubody["status"] == "active"


def test_api_rejects_invalid_priority_enum(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    bad = client.post(
        "/api/components",
        headers=auth_headers,
        json=_server_payload(priority="PRIORITY_5"),
    )
    assert bad.status_code == 422


def test_example_org_fields_seed_and_no_uob_in_natives(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    result = custom_fields_service.ensure_example_org_custom_fields(
        tenant_id="tenant-svrmon24-legacy"
    )
    assert result["created"] >= 1
    listed = client.get(
        "/api/field-definitions?origin=custom", headers=auth_headers
    )
    assert listed.status_code == 200
    keys = {item["field_key"] for item in listed.json()["items"]}
    assert "app_code" in keys
    assert "device_stage" in keys
    # Product natives must not invent UOB_* keys
    from app.cmdb.models.components import ServerFields

    assert not any(k.upper().startswith("UOB_") for k in ServerFields.model_fields)
    assert not any(k.upper().startswith("UOB_") for k in COMMON_OPTIONAL_KEYS)


def test_tenant_isolation_unchanged_for_new_fields(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    """Cross-tenant get still 404 when another tenant owns the CI."""
    from app.db import get_database
    from app.services import tenants as tenants_service
    from app.tenancy import MIGRATION_TENANT_ID

    tenants_service.ensure_migration_tenant()
    db = get_database()
    now = datetime.now(timezone.utc)
    other_tid = "tenant-c0-isolation-other"
    other_cid = "c0-other-srv-001"
    db["tenants"].update_one(
        {"tenant_id": other_tid},
        {
            "$set": {
                "tenant_id": other_tid,
                "display_name": "C0 Isolation Other",
                "slug": "c0-isolation-other",
                "status": "active",
                "is_migration_tenant": False,
                "switchable": False,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    db["cmdb_servers"].insert_one(
        {
            "component_id": other_cid,
            "component_type": "Server",
            "name": "other-tenant-server",
            "environment": "prod",
            "status": "active",
            "hostname": "other.example",
            "company": "OTHERCO",
            "serial_number": "SN-OTHER",
            "priority": "1",
            "tenant_id": other_tid,
            "custom_fields": {},
            "created_at": now,
            "updated_at": now,
        }
    )

    # Auth headers use migration tenant — must not see other tenant's CI.
    assert MIGRATION_TENANT_ID != other_tid
    missing = client.get(f"/api/components/{other_cid}", headers=auth_headers)
    assert missing.status_code == 404

    listed = client.get("/api/components", headers=auth_headers)
    assert listed.status_code == 200
    ids = {item["component_id"] for item in listed.json()["items"]}
    assert other_cid not in ids


def test_typed_indexes_include_company_serial_priority(clean_db) -> None:
    from app.db import get_database

    db = get_database()
    created = ensure_typed_cmdb_indexes(db)
    names = created[COLLECTION_SERVERS]
    assert "tenant_company_idx" in names
    assert "tenant_serial_number_idx" in names
    assert "tenant_priority_idx" in names
