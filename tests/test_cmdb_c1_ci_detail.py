"""CMDB C1 — enterprise CI detail UI (header + General + Specs) + GET/PATCH paths (0.99.10)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import __version__
from tests.frontend_paths import FRONTEND_INDEX

REPO = Path(__file__).resolve().parents[1]
CI_DETAIL_JS = REPO / "frontend" / "static" / "js" / "cmdb" / "ci-detail.js"
CMDB_JS = REPO / "frontend" / "static" / "js" / "cmdb.js"
ROUTING_JS = REPO / "frontend" / "static" / "js" / "itsm" / "routing.js"
DEEPLINKS_JS = REPO / "frontend" / "static" / "js" / "itsm" / "deeplinks.js"
CMDB_CSS = REPO / "frontend" / "static" / "css" / "cmdb.css"


def test_c1_version_bump() -> None:
    assert __version__ == "0.99.10"


def test_frontend_ci_detail_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.99.10"' in html
    assert 'id="tab-ci-detail"' in html
    assert 'id="ciDetailForm"' in html
    assert 'id="ciDetailSticky"' in html
    assert 'id="ciDetailTabStrip"' in html
    assert 'id="ciItsmRelated"' in html
    assert 'id="btnCiViewItsm"' in html
    assert 'id="btnComponentOpenCiDetail"' in html
    assert 'data-tab="ci-detail"' in html
    assert "cmdb/ci-detail.js?v=0.99.10" in html

    js = CI_DETAIL_JS.read_text(encoding="utf-8")
    assert "SVRMON24CmdbCiDetail" in js
    assert "openCiDetail" in js
    assert "registerTabHook" in js
    assert "CI_DETAIL_TABS" in js
    assert '"general"' in js
    assert '"specifications"' in js
    assert "/api/itsm/incidents?component_id=" in js
    assert "/api/itsm/changes?component_id=" in js
    # C2–C4 hook documentation in strip
    assert "work-info" in js
    assert "relationships" in js
    assert "contracts" in js

    cmdb = CMDB_JS.read_text(encoding="utf-8")
    assert "SVRMON24CmdbCiDetail" in cmdb
    assert "openCiDetail" in cmdb

    routing = ROUTING_JS.read_text(encoding="utf-8")
    assert "ci_tab" in routing
    assert "ci-detail" in routing

    deeplinks = DEEPLINKS_JS.read_text(encoding="utf-8")
    assert "SVRMON24CmdbCiDetail" in deeplinks

    css = CMDB_CSS.read_text(encoding="utf-8")
    assert ".ci-detail-sticky" in css
    assert ".ci-tab-strip" in css


def test_patch_ci_header_and_specs_round_trip(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Server",
            "name": "ci-detail-srv.example.com",
            "hostname": "ci-detail-srv.example.com",
            "environment": "Development",
            "status": "active",
            "os_family": "Linux",
            "description": "ci-detail-srv",
            "company": "ORGA",
            "system_type": "X86-based PC",
            "total_physical_memory_mb": 8192,
        },
    )
    assert created.status_code == 201, created.text
    cid = created.json()["component_id"]

    got = client.get(f"/api/components/{cid}", headers=auth_headers)
    assert got.status_code == 200
    body = got.json()
    assert body["description"] == "ci-detail-srv"
    assert body["company"] == "ORGA"
    assert body["system_type"] == "X86-based PC"
    assert body["total_physical_memory_mb"] == 8192

    # Product update verb is PUT (design said PATCH; C0 shipped PUT).
    patched = client.put(
        f"/api/components/{cid}",
        headers=auth_headers,
        json={
            "description": "updated-desc",
            "serial_number": "SER-C1",
            "supported": "yes",
            "impact": "3",
            "urgency": "2",
            "priority": "5",
            "status_reason": "Deployed",
            "manufacturer": "ExampleCorp",
            "model": "Blade",
            "product_categorization": {
                "tier1": "Hardware",
                "tier2": "Server",
                "tier3": "x86",
            },
            "lifecycle": {"installed_at": "2024-06-01T00:00:00Z"},
            "virtual_system_type": "KVM",
            "is_virtual": True,
            "dns_hostname": "ci-detail-srv.example.com",
            "domain": "example.com",
            "flash_memory_mb": 0,
            "additional_information": "c1 note",
        },
    )
    assert patched.status_code == 200, patched.text
    doc = patched.json()
    assert doc["description"] == "updated-desc"
    assert doc["serial_number"] == "SER-C1"
    assert doc["supported"] == "yes"
    assert doc["impact"] == "3"
    assert doc["priority"] == "5"
    assert doc["manufacturer"] == "ExampleCorp"
    assert doc["product_categorization"]["tier1"] == "Hardware"
    assert doc["lifecycle"]["installed_at"]
    assert doc["is_virtual"] is True
    assert doc["dns_hostname"] == "ci-detail-srv.example.com"
    assert doc["additional_information"] == "c1 note"

    again = client.get(f"/api/components/{cid}", headers=auth_headers)
    assert again.status_code == 200
    assert again.json()["serial_number"] == "SER-C1"


def test_itsm_related_lists_filter_by_component_for_ci_header(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    """CI detail header loads related INC/CHG via ITSM APIs only (N5 pattern)."""
    created = client.post(
        "/api/components",
        headers=auth_headers,
        json={
            "component_type": "Server",
            "name": "c1-itsm-ci",
            "hostname": "c1-itsm-ci.example",
            "environment": "prod",
            "status": "active",
        },
    )
    assert created.status_code == 201, created.text
    cid = created.json()["component_id"]

    inc = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={"title": "C1 linked INC", "priority": "p3", "ci_links": [{"component_id": cid}]},
    )
    assert inc.status_code == 201, inc.text

    chg = client.post(
        "/api/itsm/changes",
        headers=auth_headers,
        json={
            "title": "C1 linked CHG",
            "change_type": "normal",
            "ci_links": [{"component_id": cid}],
        },
    )
    assert chg.status_code == 201, chg.text

    inc_list = client.get(
        f"/api/itsm/incidents?component_id={cid}&limit=5", headers=auth_headers
    )
    assert inc_list.status_code == 200
    assert inc_list.json()["total"] >= 1
    assert any(i["title"] == "C1 linked INC" for i in inc_list.json()["items"])

    chg_list = client.get(
        f"/api/itsm/changes?component_id={cid}&limit=5", headers=auth_headers
    )
    assert chg_list.status_code == 200
    assert chg_list.json()["total"] >= 1
    assert any(c["title"] == "C1 linked CHG" for c in chg_list.json()["items"])


@pytest.mark.parametrize(
    "path",
    [
        "frontend/static/js/cmdb/ci-detail.js",
        "frontend/index.html",
    ],
)
def test_c1_assets_exist(path: str) -> None:
    assert (REPO / path).is_file()
