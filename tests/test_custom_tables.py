"""Custom entity tables — definitions, records, references, relationships."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.tenancy import MIGRATION_TENANT_ID

OTHER_TENANT_ID = "tenant-custom-tables-other"


def _create_server(client: TestClient, headers: dict[str, str], component_id: str) -> None:
    resp = client.post(
        "/api/components",
        headers=headers,
        json={
            "component_id": component_id,
            "component_type": "Server",
            "name": component_id,
            "hostname": f"{component_id}.example",
            "environment": "prod",
            "status": "active",
            "os_family": "Linux",
            "os_version": "9",
        },
    )
    assert resp.status_code == 201, resp.text


def test_create_table_columns_records_and_reference(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _create_server(client, auth_headers, "srv-custom-1")

    created = client.post(
        "/api/custom-tables",
        headers=auth_headers,
        json={
            "table_key": "business_services",
            "label": "Business Services",
            "description": "Tenant custom CI class",
            "columns": [
                {
                    "column_key": "tier",
                    "label": "Tier",
                    "field_type": "enum",
                    "enum_values": ["gold", "silver"],
                    "required": True,
                    "order": 0,
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["table_key"] == "business_services"
    assert body["tenant_id"] == MIGRATION_TENANT_ID
    assert len(body["columns"]) == 1

    listed = client.get("/api/custom-tables", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["storage_mode"] == "single_collection_with_table_key"
    assert any(i["table_key"] == "business_services" for i in listed.json()["items"])

    # Add reference column → Server
    with_ref = client.post(
        "/api/custom-tables/business_services/columns",
        headers=auth_headers,
        json={
            "column_key": "primary_server",
            "label": "Primary server",
            "field_type": "reference",
            "reference_table": "Server",
            "required": True,
            "order": 1,
        },
    )
    assert with_ref.status_code == 201, with_ref.text
    assert any(
        c["column_key"] == "primary_server" for c in with_ref.json()["columns"]
    )

    record = client.post(
        "/api/custom-tables/business_services/records",
        headers=auth_headers,
        json={
            "record_id": "svc-billing",
            "display_name": "Billing",
            "fields": {
                "tier": "gold",
                "primary_server": {"ref_id": "srv-custom-1", "ref_table": "Server"},
            },
        },
    )
    assert record.status_code == 201, record.text
    assert record.json()["fields"]["primary_server"]["ref_id"] == "srv-custom-1"

    got = client.get(
        "/api/custom-tables/business_services/records/svc-billing",
        headers=auth_headers,
    )
    assert got.status_code == 200
    assert got.json()["display_name"] == "Billing"

    # Bad reference table rejected
    bad = client.post(
        "/api/custom-tables/business_services/records",
        headers=auth_headers,
        json={
            "display_name": "Broken",
            "fields": {
                "tier": "silver",
                "primary_server": {"ref_id": "srv-custom-1", "ref_table": "Database"},
            },
        },
    )
    assert bad.status_code == 422


def test_reserved_table_key_and_column_crud(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    reserved = client.post(
        "/api/custom-tables",
        headers=auth_headers,
        json={"table_key": "servers", "label": "Nope"},
    )
    assert reserved.status_code == 422

    created = client.post(
        "/api/custom-tables",
        headers=auth_headers,
        json={"table_key": "cost_centers", "label": "Cost Centers"},
    )
    assert created.status_code == 201, created.text

    added = client.post(
        "/api/custom-tables/cost_centers/columns",
        headers=auth_headers,
        json={
            "column_key": "code",
            "label": "Code",
            "field_type": "string",
            "required": True,
        },
    )
    assert added.status_code == 201, added.text

    updated = client.put(
        "/api/custom-tables/cost_centers/columns/code",
        headers=auth_headers,
        json={"label": "Cost code"},
    )
    assert updated.status_code == 200, updated.text
    col = next(c for c in updated.json()["columns"] if c["column_key"] == "code")
    assert col["label"] == "Cost code"

    deleted_col = client.delete(
        "/api/custom-tables/cost_centers/columns/code",
        headers=auth_headers,
    )
    assert deleted_col.status_code == 200
    assert deleted_col.json()["columns"] == []


def test_relationship_with_custom_entity(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _create_server(client, auth_headers, "srv-rel-host")

    assert (
        client.post(
            "/api/custom-tables",
            headers=auth_headers,
            json={"table_key": "clusters", "label": "Clusters"},
        ).status_code
        == 201
    )
    rec = client.post(
        "/api/custom-tables/clusters/records",
        headers=auth_headers,
        json={"record_id": "clu-1", "display_name": "Cluster One", "fields": {}},
    )
    assert rec.status_code == 201, rec.text

    rel = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "clu-1",
            "source_table": "clusters",
            "target_component_id": "srv-rel-host",
            "target_table": "Server",
            "relationship_type": "HOSTED_ON",
            "protocol": "TCP",
            "source_port": None,
            "target_port": 22,
        },
    )
    assert rel.status_code == 201, rel.text
    body = rel.json()
    assert body["source_table"] == "clusters"
    assert body["target_table"] == "Server"
    assert body["source_component_id"] == "clu-1"

    # Custom entity without source_table must fail (not a CMDB component).
    missing = client.post(
        "/api/relationships",
        headers=auth_headers,
        json={
            "source_component_id": "clu-1",
            "target_component_id": "srv-rel-host",
            "relationship_type": "DEPENDS_ON",
        },
    )
    assert missing.status_code == 422

    refs = client.get("/api/entity-refs", headers=auth_headers)
    assert refs.status_code == 200
    ids = {i["entity_id"] for i in refs.json()["items"]}
    assert "clu-1" in ids
    assert "srv-rel-host" in ids


def test_custom_to_custom_reference_and_cross_tenant_isolation(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    assert (
        client.post(
            "/api/custom-tables",
            headers=auth_headers,
            json={"table_key": "regions", "label": "Regions"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/custom-tables",
            headers=auth_headers,
            json={
                "table_key": "sites",
                "label": "Sites",
                "columns": [
                    {
                        "column_key": "region",
                        "label": "Region",
                        "field_type": "reference",
                        "reference_table": "regions",
                        "required": True,
                    }
                ],
            },
        ).status_code
        == 201
    )
    region = client.post(
        "/api/custom-tables/regions/records",
        headers=auth_headers,
        json={"record_id": "reg-eu", "display_name": "EU", "fields": {}},
    )
    assert region.status_code == 201, region.text
    site = client.post(
        "/api/custom-tables/sites/records",
        headers=auth_headers,
        json={
            "record_id": "site-1",
            "display_name": "Dublin",
            "fields": {
                "region": {"ref_id": "reg-eu", "ref_table": "regions"},
            },
        },
    )
    assert site.status_code == 201, site.text

    # Cross-tenant docs invisible
    from app.db import get_database

    db = get_database()
    now = datetime.now(timezone.utc)
    db["cmdb_custom_table_definitions"].insert_one(
        {
            "table_key": "secret_table",
            "label": "Secret",
            "columns": [],
            "active": True,
            "tenant_id": OTHER_TENANT_ID,
            "created_at": now,
            "updated_at": now,
        }
    )
    db["cmdb_custom_records"].insert_one(
        {
            "table_key": "secret_table",
            "record_id": "secret-1",
            "display_name": "Hidden",
            "fields": {},
            "tenant_id": OTHER_TENANT_ID,
            "created_at": now,
            "updated_at": now,
        }
    )
    listed = client.get("/api/custom-tables", headers=auth_headers).json()["items"]
    assert all(i["table_key"] != "secret_table" for i in listed)
    assert (
        client.get(
            "/api/custom-tables/secret_table", headers=auth_headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/custom-tables/secret_table/records/secret-1",
            headers=auth_headers,
        ).status_code
        == 404
    )


def test_delete_table_blocked_when_referenced(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    assert (
        client.post(
            "/api/custom-tables",
            headers=auth_headers,
            json={"table_key": "owners", "label": "Owners"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/custom-tables",
            headers=auth_headers,
            json={
                "table_key": "assets",
                "label": "Assets",
                "columns": [
                    {
                        "column_key": "owner",
                        "label": "Owner",
                        "field_type": "reference",
                        "reference_table": "owners",
                    }
                ],
            },
        ).status_code
        == 201
    )
    blocked = client.delete("/api/custom-tables/owners", headers=auth_headers)
    assert blocked.status_code == 409

    # Delete dependent table first, then owners.
    assert (
        client.delete("/api/custom-tables/assets", headers=auth_headers).status_code
        == 200
    )
    assert (
        client.delete("/api/custom-tables/owners", headers=auth_headers).status_code
        == 200
    )


def test_core_cmdb_facade_unchanged(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _create_server(client, auth_headers, "srv-facade")
    listed = client.get("/api/components", headers=auth_headers)
    assert listed.status_code == 200
    assert any(i["component_id"] == "srv-facade" for i in listed.json()["items"])
    # OS/product still separate on components
    doc = client.get("/api/components/srv-facade", headers=auth_headers).json()
    assert "os_family" in doc and "os_version" in doc
    assert "os_family_version" not in doc
