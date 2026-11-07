"""Master Phase 8 — cmdb_column_configurations, locked columns, tenant scope."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.models.column_configs import (
    LOCKED_INVENTORY_COLUMNS,
    LOCKED_RELATIONSHIP_COLUMNS,
)
from app.tenancy import MIGRATION_TENANT_ID

OTHER_TENANT_ID = "tenant-colcfg-other"


def test_list_defaults_include_locked_inventory_and_relationships(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    listed = client.get("/api/column-configurations", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["collection"] == "cmdb_column_configurations"
    assert body["tenant_id"] == MIGRATION_TENANT_ID
    by_grid = {i["grid_key"]: i for i in body["items"]}
    assert set(by_grid) == {"inventory", "relationships"}

    inv = by_grid["inventory"]
    assert inv["is_default"] is True
    inv_keys = [c["column_key"] for c in inv["columns"]]
    assert inv_keys.index("os_family") < inv_keys.index("os_version")
    assert inv_keys.index("product_type") < inv_keys.index("product_version")
    assert "os_family_version" not in inv_keys
    for key in LOCKED_INVENTORY_COLUMNS | {"actions"}:
        col = next(c for c in inv["columns"] if c["column_key"] == key)
        assert col["visible"] is True
        assert col["locked"] is True

    rel = by_grid["relationships"]
    assert rel["is_default"] is True
    rel_keys = [c["column_key"] for c in rel["columns"]]
    assert "protocol" in rel_keys
    assert "source_port" in rel_keys
    assert "target_port" in rel_keys
    assert "protocol_ports" not in rel_keys
    for key in LOCKED_RELATIONSHIP_COLUMNS | {"actions"}:
        col = next(c for c in rel["columns"] if c["column_key"] == key)
        assert col["visible"] is True
        assert col["locked"] is True


def test_put_hides_optional_and_rejects_locked_hide(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    defaults = client.get(
        "/api/column-configurations/inventory", headers=auth_headers
    ).json()
    columns = []
    for col in defaults["columns"]:
        entry = {
            "column_key": col["column_key"],
            "visible": col["visible"],
            "order": col["order"],
            "width": 160 if col["column_key"] == "environment" else None,
            "pinned": "left" if col["column_key"] == "component_id" else None,
        }
        if col["column_key"] == "environment":
            entry["visible"] = False
        columns.append(entry)

    saved = client.put(
        "/api/column-configurations/inventory",
        headers=auth_headers,
        json={"columns": columns},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["is_default"] is False
    by_key = {c["column_key"]: c for c in body["columns"]}
    assert by_key["environment"]["visible"] is False
    assert by_key["environment"]["width"] == 160
    assert by_key["component_id"]["pinned"] == "left"
    assert by_key["os_family"]["visible"] is True
    assert by_key["os_version"]["visible"] is True

    # Reorder: move status before environment (still after product fields).
    reordered = sorted(body["columns"], key=lambda c: c["order"])
    status = next(c for c in reordered if c["column_key"] == "status")
    env = next(c for c in reordered if c["column_key"] == "environment")
    status_idx = reordered.index(status)
    env_idx = reordered.index(env)
    reordered[status_idx], reordered[env_idx] = reordered[env_idx], reordered[status_idx]
    payload = {
        "columns": [
            {
                "column_key": c["column_key"],
                "visible": c["visible"],
                "order": idx,
                "width": c.get("width"),
                "pinned": c.get("pinned"),
            }
            for idx, c in enumerate(reordered)
        ]
    }
    again = client.put(
        "/api/column-configurations/inventory",
        headers=auth_headers,
        json=payload,
    )
    assert again.status_code == 200, again.text
    keys = [c["column_key"] for c in again.json()["columns"] if c["visible"]]
    assert keys.index("status") < keys.index("actions")

    # Cannot hide locked OS Family.
    bad = [
        {
            "column_key": c["column_key"],
            "visible": False if c["column_key"] == "os_family" else c["visible"],
            "order": c["order"],
            "width": c.get("width"),
            "pinned": c.get("pinned"),
        }
        for c in again.json()["columns"]
    ]
    denied = client.put(
        "/api/column-configurations/inventory",
        headers=auth_headers,
        json={"columns": bad},
    )
    assert denied.status_code == 400
    assert "locked" in denied.json()["error"]["message"].lower()


def test_relationships_locked_ports_and_reset(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    defaults = client.get(
        "/api/column-configurations/relationships", headers=auth_headers
    ).json()
    columns = [
        {
            "column_key": c["column_key"],
            "visible": False if c["column_key"] == "discovery_method" else True,
            "order": c["order"],
            "width": None,
            "pinned": None,
        }
        for c in defaults["columns"]
    ]
    saved = client.put(
        "/api/column-configurations/relationships",
        headers=auth_headers,
        json={"columns": columns},
    )
    assert saved.status_code == 200, saved.text
    by_key = {c["column_key"]: c for c in saved.json()["columns"]}
    assert by_key["discovery_method"]["visible"] is False
    assert by_key["protocol"]["visible"] is True
    assert by_key["source_port"]["visible"] is True
    assert by_key["target_port"]["visible"] is True

    bad = [
        {
            "column_key": c["column_key"],
            "visible": False if c["column_key"] == "source_port" else c["visible"],
            "order": c["order"],
            "width": None,
            "pinned": None,
        }
        for c in saved.json()["columns"]
    ]
    denied = client.put(
        "/api/column-configurations/relationships",
        headers=auth_headers,
        json={"columns": bad},
    )
    assert denied.status_code == 400

    reset = client.delete(
        "/api/column-configurations/relationships", headers=auth_headers
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["is_default"] is True
    assert all(c["visible"] for c in reset.json()["columns"])


def test_unknown_grid_and_collapsed_keys_rejected(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    missing = client.get("/api/column-configurations/audit", headers=auth_headers)
    assert missing.status_code == 404

    collapsed = client.put(
        "/api/column-configurations/inventory",
        headers=auth_headers,
        json={
            "columns": [
                {
                    "column_key": "os_family_version",
                    "visible": True,
                    "order": 0,
                    "width": None,
                    "pinned": None,
                }
            ]
        },
    )
    assert collapsed.status_code == 400


def test_column_config_tenant_isolation(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    from app.db import get_database
    from app.services import tenants as tenants_service

    tenants_service.ensure_migration_tenant()
    db = get_database()
    now = datetime.now(timezone.utc)
    db["tenants"].update_one(
        {"tenant_id": OTHER_TENANT_ID},
        {
            "$set": {
                "tenant_id": OTHER_TENANT_ID,
                "display_name": "Other ColCfg Org",
                "slug": "colcfg-other",
                "status": "active",
                "is_migration_tenant": False,
                "switchable": False,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    db["cmdb_column_configurations"].insert_one(
        {
            "grid_key": "inventory",
            "tenant_id": OTHER_TENANT_ID,
            "columns": [
                {
                    "column_key": "environment",
                    "visible": False,
                    "order": 0,
                    "width": 99,
                    "pinned": None,
                }
            ],
            "created_at": now,
            "updated_at": now,
        }
    )

    # Migration-tenant Basic caller must not see other-tenant width/hide.
    mine = client.get(
        "/api/column-configurations/inventory", headers=auth_headers
    ).json()
    assert mine["tenant_id"] == MIGRATION_TENANT_ID
    env = next(c for c in mine["columns"] if c["column_key"] == "environment")
    assert env["visible"] is True
    assert env["width"] is None

    # Saving for migration tenant does not overwrite other tenant doc.
    payload = {
        "columns": [
            {
                "column_key": c["column_key"],
                "visible": c["visible"],
                "order": c["order"],
                "width": 120 if c["column_key"] == "status" else None,
                "pinned": None,
            }
            for c in mine["columns"]
        ]
    }
    saved = client.put(
        "/api/column-configurations/inventory",
        headers=auth_headers,
        json=payload,
    )
    assert saved.status_code == 200, saved.text
    other = db["cmdb_column_configurations"].find_one(
        {"tenant_id": OTHER_TENANT_ID, "grid_key": "inventory"}
    )
    assert other is not None
    assert other["columns"][0]["width"] == 99


def test_inventory_includes_custom_field_columns_and_values(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    """Active custom fields become Inventory columns (default visible) + row values."""
    created = client.post(
        "/api/custom-fields",
        headers=auth_headers,
        json={
            "field_key": "cost_center",
            "label": "Cost Center",
            "field_type": "string",
            "applies_to": ["Server"],
            "required": False,
        },
    )
    assert created.status_code == 201, created.text

    # Only Server — should still appear in catalog (Column Settings lists all).
    mw_only = client.post(
        "/api/custom-fields",
        headers=auth_headers,
        json={
            "field_key": "mw_tier",
            "label": "MW Tier",
            "field_type": "enum",
            "applies_to": ["Middleware"],
            "required": False,
            "enum_values": ["gold", "silver"],
        },
    )
    assert mw_only.status_code == 201, mw_only.text

    cfg = client.get("/api/column-configurations/inventory", headers=auth_headers)
    assert cfg.status_code == 200, cfg.text
    body = cfg.json()
    by_key = {c["column_key"]: c for c in body["columns"]}
    assert "cost_center" in by_key
    assert by_key["cost_center"]["visible"] is True
    assert by_key["cost_center"]["locked"] is False
    assert by_key["cost_center"]["source"] == "custom_field"
    assert by_key["cost_center"]["applies_to"] == ["Server"]
    assert "mw_tier" in by_key
    assert by_key["mw_tier"]["applies_to"] == ["Middleware"]
    # Locked OS/product pairs remain separate.
    assert "os_family" in by_key and "os_version" in by_key
    assert by_key["os_family"]["locked"] is True
    assert by_key["actions"]["order"] == max(c["order"] for c in body["columns"])

    # New custom fields also appear when a saved config predates them.
    baseline = [
        {
            "column_key": c["column_key"],
            "visible": c["visible"],
            "order": c["order"],
            "width": None,
            "pinned": None,
        }
        for c in body["columns"]
        if c["column_key"] not in {"cost_center", "mw_tier"}
    ]
    # Hide optional environment, keep locked columns.
    for entry in baseline:
        if entry["column_key"] == "environment":
            entry["visible"] = False
    saved = client.put(
        "/api/column-configurations/inventory",
        headers=auth_headers,
        json={"columns": baseline},
    )
    assert saved.status_code == 200, saved.text
    saved_keys = {c["column_key"]: c for c in saved.json()["columns"]}
    assert saved_keys["cost_center"]["visible"] is True
    assert saved_keys["mw_tier"]["visible"] is True
    assert saved_keys["environment"]["visible"] is False

    # Toggle off cost_center.
    toggled = []
    for c in saved.json()["columns"]:
        toggled.append(
            {
                "column_key": c["column_key"],
                "visible": False if c["column_key"] == "cost_center" else c["visible"],
                "order": c["order"],
                "width": c.get("width"),
                "pinned": c.get("pinned"),
            }
        )
    again = client.put(
        "/api/column-configurations/inventory",
        headers=auth_headers,
        json={"columns": toggled},
    )
    assert again.status_code == 200, again.text
    assert next(
        c for c in again.json()["columns"] if c["column_key"] == "cost_center"
    )["visible"] is False

    # Inventory list exposes custom_fields on rows for grid rendering.
    srv = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_id": "srv-cf-1",
            "component_type": "Server",
            "name": "cf-web",
            "hostname": "cf-web",
            "environment": "prod",
            "status": "active",
            "os_family": "RHEL",
            "os_version": "9.4",
            "custom_fields": {"cost_center": "IT-OPS"},
        },
    )
    assert srv.status_code == 201, srv.text
    listed = client.get(
        "/api/components?component_type=Server&page_size=50", headers=auth_headers
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()["inventory"]
    row = next(r for r in rows if r["component_id"] == "srv-cf-1")
    assert row["custom_fields"]["cost_center"] == "IT-OPS"
    assert row["os_family"] == "RHEL"
    assert row["os_version"] == "9.4"
