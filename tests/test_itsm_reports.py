"""ITSM report export + custom report definitions — functional coverage for 0.42.0."""

from __future__ import annotations

import csv
import io

from app import __version__
from app.db import get_itsm_database
from app.permissions import (
    PERM_ITSM_REPORTS_READ,
    PERM_ITSM_REPORTS_WRITE,
    permissions_for_role,
)
from app.tenancy import MEMBERSHIP_ROLE_MEMBER, MEMBERSHIP_ROLE_VIEWER
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_reports_slice() -> None:
    assert __version__ == "0.86.0"


def test_reports_permissions_for_roles() -> None:
    viewer = permissions_for_role(MEMBERSHIP_ROLE_VIEWER)
    member = permissions_for_role(MEMBERSHIP_ROLE_MEMBER)
    assert PERM_ITSM_REPORTS_READ in viewer
    assert PERM_ITSM_REPORTS_WRITE not in viewer
    assert PERM_ITSM_REPORTS_READ in member
    assert PERM_ITSM_REPORTS_WRITE in member


def _create_incident(client: TestClient, auth_headers: dict[str, str], **overrides):
    body = {
        "title": "Report export sample",
        "description": "For export coverage",
        "priority": "p1",
        "category": "network",
        "service_tier": "tier1",
    }
    body.update(overrides)
    resp = client.post("/api/itsm/incidents", headers=auth_headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_dashboard_export_csv_and_xlsx(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    _create_incident(client, auth_headers)

    csv_resp = client.get(
        "/api/itsm/dashboard/export?format=csv&window_days=30&include_tickets=true",
        headers=auth_headers,
    )
    assert csv_resp.status_code == 200, csv_resp.text
    assert "text/csv" in csv_resp.headers["content-type"]
    assert csv_resp.headers.get("x-export-format") == "csv"
    assert int(csv_resp.headers.get("x-export-count") or "0") >= 1
    text = csv_resp.content.decode("utf-8-sig")
    assert "# Summary KPIs" in text
    assert "open_incidents" in text
    assert "Ticket detail" in text or "incident" in text.lower()
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    assert any("open_incidents" in row for row in rows)

    xlsx_resp = client.get(
        "/api/itsm/dashboard/export?format=xlsx&window_days=7",
        headers=auth_headers,
    )
    assert xlsx_resp.status_code == 200, xlsx_resp.text
    assert "spreadsheetml" in xlsx_resp.headers["content-type"]
    wb = load_workbook(io.BytesIO(xlsx_resp.content))
    assert "Summary KPIs" in wb.sheetnames or len(wb.sheetnames) >= 1
    assert any("KPI" in name or "Daily" in name or "Ticket" in name for name in wb.sheetnames)


def test_custom_report_crud_run_export_and_tenant_isolation(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    inc = _create_incident(client, auth_headers)
    tid = inc["tenant_id"]

    create = client.post(
        "/api/itsm/reports/definitions",
        headers=auth_headers,
        json={
            "name": "P1 network open work",
            "description": "Export-focused custom report",
            "metrics": ["open_incidents", "sla_breaches", "ticket_rows"],
            "filters": {
                "ticket_types": ["incident"],
                "priorities": ["p1"],
                "category": "network",
                "service_tier": "tier1",
                "window_days": 30,
            },
            "columns": [
                "ticket_type",
                "ticket_id",
                "title",
                "status",
                "priority",
                "category",
                "service_tier",
                "created_at",
            ],
        },
    )
    assert create.status_code == 201, create.text
    report = create.json()
    report_id = report["report_id"]
    assert report["tenant_id"] == tid
    assert report["name"] == "P1 network open work"

    listed = client.get("/api/itsm/reports/definitions", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] >= 1
    assert any(item["report_id"] == report_id for item in listed.json()["items"])

    patched = client.patch(
        f"/api/itsm/reports/definitions/{report_id}",
        headers=auth_headers,
        json={"description": "Updated description"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["description"] == "Updated description"

    run = client.post(
        f"/api/itsm/reports/definitions/{report_id}/run",
        headers=auth_headers,
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["report_id"] == report_id
    metrics = {row["metric"]: row["value"] for row in body["summary_metrics"]}
    assert "open_incidents" in metrics
    assert body["ticket_row_count"] >= 1
    assert body["ticket_rows"][0]["priority"] == "p1"
    assert body["ticket_rows"][0]["category"] == "network"

    export = client.get(
        f"/api/itsm/reports/definitions/{report_id}/export?format=csv",
        headers=auth_headers,
    )
    assert export.status_code == 200, export.text
    assert "text/csv" in export.headers["content-type"]
    export_text = export.content.decode("utf-8-sig")
    assert "open_incidents" in export_text
    assert "Ticket rows" in export_text or "ticket_id" in export_text

    # Tenant isolation: planted foreign doc must never appear via API.
    foreign_id = "RPT-FOREIGN01"
    get_itsm_database()["itsm_report_definitions"].insert_one(
        {
            "tenant_id": "tenant-other-isolation",
            "report_id": foreign_id,
            "name": "Foreign report",
            "metrics": ["open_incidents"],
            "filters": {"ticket_types": ["incident"], "window_days": 7},
            "columns": ["ticket_id", "title"],
        }
    )
    foreign_get = client.get(
        f"/api/itsm/reports/definitions/{foreign_id}",
        headers=auth_headers,
    )
    assert foreign_get.status_code == 404

    deleted = client.delete(
        f"/api/itsm/reports/definitions/{report_id}",
        headers=auth_headers,
    )
    assert deleted.status_code == 204, deleted.text
    missing = client.get(
        f"/api/itsm/reports/definitions/{report_id}",
        headers=auth_headers,
    )
    assert missing.status_code == 404


def test_frontend_wires_report_export_ui(client: TestClient) -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.86.0"' in html
    assert "btnExportItsmReportsCsv" in html
    assert "btnExportItsmReportsXlsx" in html
    assert "itsmCustomReportForm" in html
    assert "itsm/reports.js?v=0.86.0" in html
    assert "itsm:reports:write" in html
