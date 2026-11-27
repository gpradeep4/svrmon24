"""CMDB C4 — Contracts + Outage + Impacted Areas (0.99.12)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__
from tests.frontend_paths import FRONTEND_INDEX

REPO = Path(__file__).resolve().parents[1]
CI_DETAIL_JS = REPO / "frontend" / "static" / "js" / "cmdb" / "ci-detail.js"
CMDB_CSS = REPO / "frontend" / "static" / "css" / "cmdb.css"
CONTRACTS_SVC = REPO / "app" / "cmdb" / "services" / "contracts.py"
OUTAGES_SVC = REPO / "app" / "cmdb" / "services" / "outages.py"
IMPACT_SVC = REPO / "app" / "cmdb" / "services" / "impacted_areas.py"
TENANCY = REPO / "app" / "tenancy.py"


def test_c4_version_bump() -> None:
    assert __version__ == "0.99.12"


def test_frontend_c4_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.12"' in html
    assert "cmdb/ci-detail.js?v=0.99.12" in html

    js = CI_DETAIL_JS.read_text(encoding="utf-8")
    assert 'id: "contracts", label: "Contracts", active: true' in js
    assert 'id: "outage", label: "Outage", active: true' in js
    assert 'id: "impacted-areas", label: "Impacted Areas", active: true' in js
    assert 'registerTabHook("contracts"' in js
    assert 'registerTabHook("outage"' in js
    assert 'registerTabHook("impacted-areas"' in js
    assert "/api/components/" in js and "/contracts" in js
    assert "/outages" in js
    assert "/impacted-areas" in js
    assert "itsm_change_ref" in js
    assert "itsm_ref" in js
    assert "No contracts were found related to this CI." in js
    assert "Create renewal change" in js
    assert "Create related incident" in js

    css = CMDB_CSS.read_text(encoding="utf-8")
    assert ".ci-contracts-actions" in css
    assert ".ci-outage-actions" in css
    assert ".ci-impact-actions" in css

    assert "cmdb_contracts" in CONTRACTS_SVC.read_text(encoding="utf-8")
    assert "cmdb_ci_contract_links" in CONTRACTS_SVC.read_text(encoding="utf-8")
    assert "cmdb_ci_outages" in OUTAGES_SVC.read_text(encoding="utf-8")
    assert "cmdb_impacted_areas" in IMPACT_SVC.read_text(encoding="utf-8")

    tenancy = TENANCY.read_text(encoding="utf-8")
    assert "cmdb_contracts" in tenancy
    assert "cmdb_ci_outages" in tenancy
    assert "cmdb_impacted_areas" in tenancy


def _create_server(client: TestClient, headers: dict[str, str], name: str) -> str:
    created = client.post(
        "/api/components",
        headers=headers,
        json={
            "component_type": "Server",
            "name": name,
            "hostname": name,
            "environment": "Development",
            "status": "active",
            "os_family": "Linux",
            "os_version": "8.9",
            "ip_address": "10.4.4.1",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["component_id"]


def test_contracts_crud_link_unlink_and_itsm_change_ref(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    srv = _create_server(client, auth_headers, "c4-ctr-srv.example.com")

    empty = client.get(
        f"/api/components/{srv}/contracts", headers=auth_headers
    )
    assert empty.status_code == 200
    assert empty.json()["total"] == 0

    # Create + link in one shot with optional renewal Change ref.
    linked = client.post(
        f"/api/components/{srv}/contracts",
        headers=auth_headers,
        json={
            "relationship_name": "covered_by",
            "contract": {
                "contract_type": "support",
                "description": "Hardware support 24x7",
                "start_date": "2026-01-01",
                "end_date": "2027-01-01",
                "status": "active",
                "vendor": "Acme Support",
                "itsm_change_ref": {
                    "module": "change",
                    "ticket_id": "CHG-C4-RENEW",
                },
            },
        },
    )
    assert linked.status_code == 201, linked.text
    row = linked.json()
    assert row["link_id"].startswith("clk-")
    assert row["contract_id"].startswith("ctr-")
    assert row["description"] == "Hardware support 24x7"
    assert row["itsm_change_ref"]["ticket_id"] == "CHG-C4-RENEW"
    link_id = row["link_id"]
    contract_id = row["contract_id"]

    # Invalid itsm_change_ref module rejected
    bad = client.post(
        f"/api/components/{srv}/contracts",
        headers=auth_headers,
        json={
            "contract": {
                "description": "bad",
                "itsm_change_ref": {
                    "module": "incident",
                    "ticket_id": "INC-X",
                },
            }
        },
    )
    assert bad.status_code == 422

    # Standalone contract + search + link existing
    created = client.post(
        "/api/contracts",
        headers=auth_headers,
        json={
            "contract_type": "lease",
            "description": "Rack lease Q1",
            "status": "active",
            "vendor": "ColoCo",
        },
    )
    assert created.status_code == 201, created.text
    other_id = created.json()["contract_id"]

    searched = client.get(
        "/api/contracts?q=Rack", headers=auth_headers
    )
    assert searched.status_code == 200
    assert any(i["contract_id"] == other_id for i in searched.json()["items"])

    linked2 = client.post(
        f"/api/components/{srv}/contracts",
        headers=auth_headers,
        json={"contract_id": other_id, "relationship_name": "leased_under"},
    )
    assert linked2.status_code == 201, linked2.text

    # Duplicate link → 409
    dup = client.post(
        f"/api/components/{srv}/contracts",
        headers=auth_headers,
        json={"contract_id": other_id},
    )
    assert dup.status_code == 409

    listed = client.get(
        f"/api/components/{srv}/contracts", headers=auth_headers
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 2

    # Delete contract while linked → 409
    blocked = client.delete(
        f"/api/contracts/{contract_id}", headers=auth_headers
    )
    assert blocked.status_code == 409

    unlinked = client.delete(
        f"/api/components/{srv}/contracts/{link_id}", headers=auth_headers
    )
    assert unlinked.status_code == 200
    assert unlinked.json()["ok"] is True

    deleted = client.delete(
        f"/api/contracts/{contract_id}", headers=auth_headers
    )
    assert deleted.status_code == 200

    missing = client.get(
        "/api/components/srv-does-not-exist/contracts", headers=auth_headers
    )
    assert missing.status_code == 404


def test_outages_crud_and_itsm_ref(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    srv = _create_server(client, auth_headers, "c4-out-srv.example.com")

    empty = client.get(
        f"/api/components/{srv}/outages", headers=auth_headers
    )
    assert empty.status_code == 200
    assert empty.json()["total"] == 0

    created = client.post(
        f"/api/components/{srv}/outages",
        headers=auth_headers,
        json={
            "unavailability_class": "planned",
            "unavailability_type": "maintenance",
            "status": "scheduled",
            "assignment_status": "Assigned",
            "summary": "Firmware window",
            "starts_at": "2026-12-01T02:00:00Z",
            "ends_at": "2026-12-01T04:00:00Z",
            "itsm_ref": {"module": "change", "ticket_id": "CHG-C4-OUT"},
        },
    )
    assert created.status_code == 201, created.text
    row = created.json()
    oid = row["outage_id"]
    assert oid.startswith("out-")
    assert row["itsm_ref"]["ticket_id"] == "CHG-C4-OUT"

    # Bad ITSM module
    bad = client.post(
        f"/api/components/{srv}/outages",
        headers=auth_headers,
        json={
            "summary": "bad",
            "itsm_ref": {"module": "cmdb", "ticket_id": "X"},
        },
    )
    assert bad.status_code == 422

    detail = client.get(
        f"/api/components/{srv}/outages/{oid}", headers=auth_headers
    )
    assert detail.status_code == 200
    assert detail.json()["summary"] == "Firmware window"

    patched = client.patch(
        f"/api/components/{srv}/outages/{oid}",
        headers=auth_headers,
        json={
            "status": "in_progress",
            "itsm_ref": {"module": "incident", "ticket_id": "INC-C4-OUT"},
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "in_progress"
    assert patched.json()["itsm_ref"]["module"] == "incident"

    deleted = client.delete(
        f"/api/components/{srv}/outages/{oid}", headers=auth_headers
    )
    assert deleted.status_code == 200
    gone = client.get(
        f"/api/components/{srv}/outages/{oid}", headers=auth_headers
    )
    assert gone.status_code == 404


def test_impacted_areas_crud_and_empty_validation(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    srv = _create_server(client, auth_headers, "c4-imp-srv.example.com")

    empty = client.get(
        f"/api/components/{srv}/impacted-areas", headers=auth_headers
    )
    assert empty.status_code == 200
    assert empty.json()["total"] == 0

    # Empty payload rejected
    bad = client.post(
        f"/api/components/{srv}/impacted-areas",
        headers=auth_headers,
        json={},
    )
    assert bad.status_code == 422

    created = client.post(
        f"/api/components/{srv}/impacted-areas",
        headers=auth_headers,
        json={
            "company": "UOBS",
            "region": "APAC",
            "site_group": "SG-DC",
            "site": "SG1",
            "organization": "SIS",
            "department": "Ops",
        },
    )
    assert created.status_code == 201, created.text
    area = created.json()
    area_id = area["area_id"]
    assert area_id.startswith("area-")
    assert area["company"] == "UOBS"

    patched = client.patch(
        f"/api/components/{srv}/impacted-areas/{area_id}",
        headers=auth_headers,
        json={"department": "Platform"},
    )
    assert patched.status_code == 200
    assert patched.json()["department"] == "Platform"

    listed = client.get(
        f"/api/components/{srv}/impacted-areas", headers=auth_headers
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    deleted = client.delete(
        f"/api/components/{srv}/impacted-areas/{area_id}",
        headers=auth_headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    missing = client.get(
        "/api/components/srv-does-not-exist/impacted-areas",
        headers=auth_headers,
    )
    assert missing.status_code == 404
