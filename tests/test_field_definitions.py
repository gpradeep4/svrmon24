"""Master Phase 7 — cmdb_field_definitions, builtins, migration, facade."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models.custom_fields import BUILTIN_FIELD_KEYS
from app.tenancy import MIGRATION_TENANT_ID


def test_field_definitions_seed_builtins_and_list(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    listed = client.get("/api/field-definitions", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["collection"] == "cmdb_field_definitions"
    assert body["tenant_id"] == MIGRATION_TENANT_ID
    keys = {i["field_key"] for i in body["items"]}
    assert BUILTIN_FIELD_KEYS.issubset(keys)
    builtins = [i for i in body["items"] if i["origin"] == "builtin"]
    assert len(builtins) == 4
    for item in builtins:
        assert item["storage"] == "native"
        assert item["locked"] is True
        assert item["field_key"] in BUILTIN_FIELD_KEYS

    # OS + product pairs remain separate keys (never collapsed).
    assert "os_family" in keys and "os_version" in keys
    assert "product_type" in keys and "product_version" in keys
    assert "os_family_version" not in keys
    assert "product_type_version" not in keys


def test_custom_fields_facade_excludes_builtins(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    # Touch field-definitions so builtins exist.
    client.get("/api/field-definitions", headers=auth_headers)

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
    assert created.json()["origin"] == "custom"
    assert created.json()["storage"] == "custom_fields"

    facade = client.get("/api/custom-fields", headers=auth_headers)
    assert facade.status_code == 200
    facade_keys = {i["field_key"] for i in facade.json()["items"]}
    assert "cost_center" in facade_keys
    assert facade_keys.isdisjoint(BUILTIN_FIELD_KEYS)

    # Canonical list can filter custom-only too.
    custom_only = client.get(
        "/api/field-definitions?origin=custom", headers=auth_headers
    )
    assert {i["field_key"] for i in custom_only.json()["items"]} == {"cost_center"}


def test_builtin_cannot_delete_or_collapse(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    client.get("/api/field-definitions", headers=auth_headers)

    deleted = client.delete("/api/field-definitions/os_family", headers=auth_headers)
    assert deleted.status_code == 400

    collapsed = client.put(
        "/api/field-definitions/os_family",
        headers=auth_headers,
        json={"applies_to": ["Server", "Network"]},
    )
    assert collapsed.status_code == 400

    # Label tweak is allowed; applies_to / storage stay locked.
    relabel = client.put(
        "/api/field-definitions/os_family",
        headers=auth_headers,
        json={"label": "OS Family (Server)"},
    )
    assert relabel.status_code == 200, relabel.text
    body = relabel.json()
    assert body["label"] == "OS Family (Server)"
    assert body["applies_to"] == ["Server"]
    assert body["storage"] == "native"
    assert body["origin"] == "builtin"

    reserved = client.post(
        "/api/field-definitions",
        headers=auth_headers,
        json={
            "field_key": "os_version",
            "label": "Hijack",
            "field_type": "string",
            "applies_to": ["*"],
        },
    )
    assert reserved.status_code == 422


def test_custom_values_still_attach_required_and_enum(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post(
        "/api/field-definitions",
        headers=auth_headers,
        json={
            "field_key": "tier",
            "label": "Tier",
            "field_type": "enum",
            "applies_to": ["Application"],
            "required": True,
            "enum_values": ["gold", "silver"],
            "description": "Service tier",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["description"] == "Service tier"

    missing = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Application",
            "name": "portal",
            "environment": "prod",
            "application_name": "portal",
        },
    )
    assert missing.status_code == 422

    bad_enum = client.post(
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
    assert bad_enum.status_code == 422

    ok = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Application",
            "name": "portal",
            "environment": "prod",
            "application_name": "portal",
            "custom_fields": {"tier": "gold"},
        },
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["custom_fields"]["tier"] == "gold"

    # Native builtins must not be stuffed into custom_fields.
    native_in_cf = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Server",
            "name": "srv",
            "environment": "lab",
            "hostname": "srv",
            "os_family": "RHEL",
            "os_version": "9",
            "custom_fields": {"os_family": "Nope"},
        },
    )
    assert native_in_cf.status_code == 422


def test_migrate_legacy_custom_field_definitions(clean_db) -> None:
    from datetime import datetime, timezone

    from app.db import get_database
    from app.services.bootstrap import ensure_tenancy_ready
    from app.services.field_defs_migrate import migrate_custom_fields_to_cmdb
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    db = get_database()
    now = datetime.now(timezone.utc)
    db["custom_field_definitions"].insert_one(
        {
            "field_key": "legacy_owner",
            "label": "Legacy Owner",
            "field_type": "string",
            "applies_to": ["*"],
            "required": False,
            "enum_values": [],
            # intentionally missing tenant_id — migrate stamps default
            "created_at": now,
            "updated_at": now,
        }
    )

    ensure_tenancy_ready()
    result = migrate_custom_fields_to_cmdb(
        db, default_tenant_id=MIGRATION_TENANT_ID, remove_legacy=False
    )
    assert result["ok"] is True
    assert result["migrated"] >= 1 or result["skipped_existing"] >= 1

    doc = db["cmdb_field_definitions"].find_one(
        {"field_key": "legacy_owner", "tenant_id": MIGRATION_TENANT_ID}
    )
    assert doc is not None
    assert doc["origin"] == "custom"
    assert doc["storage"] == "custom_fields"
    assert doc["tenant_id"] == MIGRATION_TENANT_ID

    # Builtins seeded
    for key in BUILTIN_FIELD_KEYS:
        b = db["cmdb_field_definitions"].find_one(
            {"field_key": key, "tenant_id": MIGRATION_TENANT_ID}
        )
        assert b is not None
        assert b["origin"] == "builtin"
        assert b["storage"] == "native"
        assert b["locked"] is True

    # Idempotent re-run
    again = migrate_custom_fields_to_cmdb(db, default_tenant_id=MIGRATION_TENANT_ID)
    assert again["ok"] is True
    assert again["migrated"] == 0


def test_field_definition_applies_to_filter(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    client.post(
        "/api/field-definitions",
        headers=auth_headers,
        json={
            "field_key": "rack",
            "label": "Rack",
            "field_type": "string",
            "applies_to": ["Server"],
        },
    )
    client.post(
        "/api/field-definitions",
        headers=auth_headers,
        json={
            "field_key": "app_code",
            "label": "App Code",
            "field_type": "string",
            "applies_to": ["Application"],
        },
    )
    servers = client.get(
        "/api/field-definitions?component_type=Server&origin=custom",
        headers=auth_headers,
    )
    assert servers.status_code == 200
    keys = {i["field_key"] for i in servers.json()["items"]}
    assert "rack" in keys
    assert "app_code" not in keys

    # Builtins for Server include OS pair only.
    server_all = client.get(
        "/api/field-definitions?component_type=Server", headers=auth_headers
    )
    skeys = {i["field_key"] for i in server_all.json()["items"]}
    assert "os_family" in skeys and "os_version" in skeys
    assert "product_type" not in skeys
