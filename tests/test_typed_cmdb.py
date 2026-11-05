"""Master Phase 6 — typed CMDB collections, migration, and facade CRUD."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.tenancy import MIGRATION_TENANT_ID, TYPED_CMDB_COLLECTIONS


def _now():
    return datetime.now(timezone.utc)


TYPE_PAYLOADS = {
    "Server": {
        "component_id": "typed-srv-1",
        "component_type": "Server",
        "name": "typed-server",
        "environment": "lab",
        "status": "active",
        "hostname": "typed-srv.example",
        "ip_address": "10.1.1.1",
        "os_family": "RHEL",
        "os_version": "9.4",
    },
    "Network": {
        "component_id": "typed-net-1",
        "component_type": "Network",
        "name": "typed-edge",
        "environment": "lab",
        "status": "active",
        "device_name": "lb-typed",
        "device_type": "load_balancer",
        "management_ip": "10.1.0.1",
        "listener_port": 443,
    },
    "Middleware": {
        "component_id": "typed-mware-1",
        "component_type": "Middleware",
        "name": "typed-wls",
        "environment": "lab",
        "status": "active",
        "product_type": "WebLogic",
        "product_version": "14.1.1",
        "listen_port": 7001,
    },
    "Database": {
        "component_id": "typed-db-1",
        "component_type": "Database",
        "name": "typed-oracle",
        "environment": "lab",
        "status": "active",
        "product_type": "Oracle",
        "product_version": "19c",
        "endpoint": "db.example:1521/ORCL",
        "listen_port": 1521,
    },
    "Application": {
        "component_id": "typed-app-1",
        "component_type": "Application",
        "name": "typed-billing",
        "environment": "lab",
        "status": "active",
        "application_name": "Billing",
        "application_type": "backend",
        "service_url": "https://billing.example",
        "owner": "finance",
    },
}

COLLECTION_BY_TYPE = {
    "Server": "cmdb_servers",
    "Network": "cmdb_network",
    "Middleware": "cmdb_middleware",
    "Database": "cmdb_databases",
    "Application": "cmdb_applications",
}


def test_crud_persists_to_typed_collection_per_type(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.db import get_database

    db = get_database()
    for ctype, payload in TYPE_PAYLOADS.items():
        created = client.post("/api/components", headers=auth_headers, json=payload)
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["component_type"] == ctype
        assert body["tenant_id"] == MIGRATION_TENANT_ID
        assert body.get("os_family") == payload.get("os_family")
        assert body.get("product_type") == payload.get("product_type")

        coll_name = COLLECTION_BY_TYPE[ctype]
        raw = db[coll_name].find_one({"component_id": payload["component_id"]})
        assert raw is not None, f"expected doc in {coll_name}"
        assert raw["tenant_id"] == MIGRATION_TENANT_ID
        # Not dual-written to legacy polymorphic collection on create
        assert (
            db["components"].find_one({"component_id": payload["component_id"]}) is None
        )

        fetched = client.get(
            f"/api/components/{payload['component_id']}", headers=auth_headers
        )
        assert fetched.status_code == 200
        assert fetched.json()["component_id"] == payload["component_id"]

        updated = client.put(
            f"/api/components/{payload['component_id']}",
            headers=auth_headers,
            json={"status": "inactive"},
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "inactive"
        assert db[coll_name].find_one({"component_id": payload["component_id"]})[
            "status"
        ] == "inactive"

        deleted = client.delete(
            f"/api/components/{payload['component_id']}?confirmed=true",
            headers=auth_headers,
        )
        assert deleted.status_code == 200
        assert db[coll_name].find_one({"component_id": payload["component_id"]}) is None


def test_list_unions_typed_collections(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    for payload in TYPE_PAYLOADS.values():
        assert (
            client.post("/api/components", headers=auth_headers, json=payload).status_code
            == 201
        )

    listed = client.get("/api/components?page_size=50", headers=auth_headers)
    assert listed.status_code == 200
    data = listed.json()
    assert data["total"] == 5
    assert data.get("storage") == "typed_cmdb"
    assert set(data.get("collections") or []) == set(TYPED_CMDB_COLLECTIONS)
    ids = {i["component_id"] for i in data["items"]}
    assert ids == {p["component_id"] for p in TYPE_PAYLOADS.values()}

    servers = client.get(
        "/api/components?component_type=Server", headers=auth_headers
    )
    assert servers.status_code == 200
    assert servers.json()["total"] == 1
    assert servers.json()["collections"] == ["cmdb_servers"]


def test_migrate_legacy_components_to_typed(clean_db) -> None:
    from app.db import get_database
    from app.services.bootstrap import ensure_tenancy_ready
    from app.services.cmdb_migrate import migrate_components_to_typed
    from app.services import components as components_service

    ensure_tenancy_ready()
    db = get_database()
    now = _now()
    legacy_docs = [
        {
            "component_id": "mig-srv-1",
            "component_type": "Server",
            "name": "migrate-server",
            "environment": "prod",
            "status": "active",
            "hostname": "mig.example",
            "os_family": "Linux",
            "os_version": "9",
            "tenant_id": MIGRATION_TENANT_ID,
            "custom_fields": {},
            "created_at": now,
            "updated_at": now,
        },
        {
            "component_id": "mig-db-1",
            "component_type": "Database",
            "name": "migrate-db",
            "environment": "prod",
            "status": "active",
            "product_type": "Postgres",
            "product_version": "16",
            "tenant_id": MIGRATION_TENANT_ID,
            "custom_fields": {},
            "created_at": now,
            "updated_at": now,
        },
        {
            "component_id": "mig-net-1",
            "component_type": "Network",
            "name": "migrate-net",
            "environment": "prod",
            "status": "active",
            "device_name": "sw-1",
            # missing tenant_id — migrator stamps default
            "custom_fields": {},
            "created_at": now,
            "updated_at": now,
        },
    ]
    db["components"].insert_many(legacy_docs)

    result = migrate_components_to_typed(db, default_tenant_id=MIGRATION_TENANT_ID)
    assert result["ok"] is True
    assert result["migrated"] == 3
    assert result["by_collection"]["cmdb_servers"] == 1
    assert result["by_collection"]["cmdb_databases"] == 1
    assert result["by_collection"]["cmdb_network"] == 1

    assert db["cmdb_servers"].find_one({"component_id": "mig-srv-1"}) is not None
    assert db["cmdb_databases"].find_one({"component_id": "mig-db-1"}) is not None
    net = db["cmdb_network"].find_one({"component_id": "mig-net-1"})
    assert net is not None
    assert net["tenant_id"] == MIGRATION_TENANT_ID
    # Legacy retained by default
    assert db["components"].count_documents({}) == 3

    # Idempotent re-run
    again = migrate_components_to_typed(db)
    assert again["migrated"] == 0
    assert again["skipped_existing"] == 3

    # Facade reads migrated typed docs
    listed = components_service.list_components(tenant_id=MIGRATION_TENANT_ID)
    assert listed["total"] == 3
    assert listed["storage"] == "typed_cmdb"


def test_cross_type_component_id_uniqueness(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    server = {
        "component_id": "shared-id-1",
        "component_type": "Server",
        "name": "s1",
        "environment": "lab",
        "hostname": "s1.example",
        "os_family": "Linux",
        "os_version": "9",
    }
    assert (
        client.post("/api/components", headers=auth_headers, json=server).status_code
        == 201
    )
    conflict = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_id": "shared-id-1",
            "component_type": "Application",
            "name": "app1",
            "environment": "lab",
            "application_name": "App1",
        },
    )
    assert conflict.status_code == 409


def test_dashboard_counts_typed_collections(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    for payload in (
        TYPE_PAYLOADS["Server"],
        TYPE_PAYLOADS["Database"],
        TYPE_PAYLOADS["Application"],
    ):
        assert (
            client.post("/api/components", headers=auth_headers, json=payload).status_code
            == 201
        )
    dash = client.get("/api/dashboard/summary", headers=auth_headers)
    assert dash.status_code == 200
    body = dash.json()
    assert body["total_components"] == 3
    assert body.get("cmdb_storage") == "typed"
    assert body["components_by_type"].get("Server") == 1
    assert body["components_by_type"].get("Database") == 1
    assert body["components_by_type"].get("Application") == 1
