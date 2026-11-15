"""CMDB inventory bulk-update, import, and export API tests."""

from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook


def _server_payload(**overrides):
    base = {
        "component_id": "srv-web01",
        "component_type": "Server",
        "name": "web-01",
        "environment": "prod",
        "status": "active",
        "hostname": "web-01.example.com",
        "ip_address": "10.0.0.11",
        "os_family": "RHEL",
        "os_version": "9.4",
    }
    base.update(overrides)
    return base


def _seed(client: TestClient, headers: dict[str, str]) -> None:
    payloads = [
        _server_payload(component_id="srv-a", name="alpha", hostname="alpha", environment="prod"),
        _server_payload(
            component_id="srv-b",
            name="beta",
            hostname="beta",
            environment="nonprod",
            status="inactive",
            os_family="Windows",
            os_version="2022",
        ),
        {
            "component_id": "mware-1",
            "component_type": "Middleware",
            "name": "wls",
            "environment": "prod",
            "product_type": "WebLogic",
            "product_version": "14.1.1",
            "listen_port": 7001,
        },
    ]
    for payload in payloads:
        resp = client.post("/api/components", headers=headers, json=payload)
        assert resp.status_code == 201, resp.text


def test_filter_options(client: TestClient, auth_headers: dict[str, str], clean_db) -> None:
    _seed(client, auth_headers)
    resp = client.get("/api/components/filter-options", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "prod" in data["environments"]
    assert "nonprod" in data["environments"]
    assert "active" in data["statuses"]
    assert "Server" in data["component_types"]
    assert "RHEL" in data["os_families"]
    assert "WebLogic" in data["product_types"]


def test_bulk_update_status_and_environment(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed(client, auth_headers)
    resp = client.post(
        "/api/components/bulk-update",
        headers=auth_headers,
        json={
            "component_ids": ["srv-a", "srv-b", "missing-id"],
            "status": "decommissioned",
            "environment": "lab",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["updated"] == 2
    assert sorted(body["updated_ids"]) == ["srv-a", "srv-b"]
    assert body["missing_ids"] == ["missing-id"]

    a = client.get("/api/components/srv-a", headers=auth_headers).json()
    b = client.get("/api/components/srv-b", headers=auth_headers).json()
    assert a["status"] == "decommissioned"
    assert a["environment"] == "lab"
    assert b["status"] == "decommissioned"
    assert b["environment"] == "lab"
    # Unselected row unchanged
    m = client.get("/api/components/mware-1", headers=auth_headers).json()
    assert m["status"] == "active"
    assert m["environment"] == "prod"


def test_bulk_update_requires_fields(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed(client, auth_headers)
    resp = client.post(
        "/api/components/bulk-update",
        headers=auth_headers,
        json={"component_ids": ["srv-a"]},
    )
    assert resp.status_code == 422


def test_export_csv_respects_filters(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed(client, auth_headers)
    resp = client.get(
        "/api/components/export?format=csv&component_type=Server&environment=prod",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert "text/csv" in resp.headers["content-type"]
    assert resp.headers.get("x-export-count") == "1"
    text = resp.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["component_id"] == "srv-a"
    assert rows[0]["os_family"] == "RHEL"
    assert rows[0]["os_version"] == "9.4"
    assert "product_type" in rows[0]


def test_export_xlsx(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _seed(client, auth_headers)
    resp = client.get("/api/components/export?format=xlsx", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert "spreadsheetml" in resp.headers["content-type"]
    wb = load_workbook(io.BytesIO(resp.content), read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0][0] == "component_id"
    assert len(rows) == 4  # header + 3 components
    wb.close()


def test_import_csv_dry_run_and_commit(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    csv_body = (
        "component_type,name,environment,status,hostname,os_family,os_version\n"
        "Server,import-one,lab,active,imp-1.local,RHEL,9.4\n"
        "Server,,lab,active,bad-row.local,RHEL,9.4\n"
    ).encode("utf-8")
    files = {"file": ("inventory.csv", csv_body, "text/csv")}

    preview = client.post(
        "/api/components/import?dry_run=true",
        headers=auth_headers,
        files=files,
    )
    assert preview.status_code == 200, preview.text
    report = preview.json()
    assert report["dry_run"] is True
    assert report["total_rows"] == 2
    assert report["valid_rows"] == 1
    assert report["invalid_rows"] == 1
    assert report["created"] == 0
    assert "component_type" in report["mapping"].values()

    # Nothing persisted yet
    listed = client.get("/api/components", headers=auth_headers).json()
    assert listed["total"] == 0

    commit = client.post(
        "/api/components/import?dry_run=false",
        headers=auth_headers,
        files={"file": ("inventory.csv", csv_body, "text/csv")},
    )
    assert commit.status_code == 200, commit.text
    committed = commit.json()
    assert committed["created"] == 1
    assert committed["invalid_rows"] == 1

    listed = client.get("/api/components?q=import-one", headers=auth_headers).json()
    assert listed["total"] == 1
    inv = listed["inventory"][0]
    assert inv["os_family"] == "RHEL"
    assert inv["os_version"] == "9.4"
    assert inv["product_type"] == "—"


def test_import_xlsx_with_explicit_mapping(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["Type", "Display Name", "Env", "Status"])
    ws.append(["Middleware", "mq-broker", "prod", "active"])
    buf = io.BytesIO()
    wb.save(buf)
    xlsx_bytes = buf.getvalue()

    mapping = {
        "Type": "component_type",
        "Display Name": "name",
        "Env": "environment",
        "Status": "status",
    }
    resp = client.post(
        "/api/components/import?dry_run=false",
        headers=auth_headers,
        files={"file": ("bulk.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapping": __import__("json").dumps(mapping)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 1
    assert body["format"] == "xlsx"
    listed = client.get(
        "/api/components?component_type=Middleware", headers=auth_headers
    ).json()
    assert listed["total"] == 1
    assert listed["items"][0]["name"] == "mq-broker"


def test_import_template_and_fields(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    fields = client.get("/api/components/import/fields", headers=auth_headers)
    assert fields.status_code == 200
    assert "component_type" in fields.json()["fields"]
    assert "name" in fields.json()["required"]

    tmpl = client.get("/api/components/import/template?format=csv", headers=auth_headers)
    assert tmpl.status_code == 200
    assert b"component_type" in tmpl.content
