"""ITSM N5 — CMDB↔ITSM deep-links, CI filter, impact panel markers (0.64.0)."""

from __future__ import annotations

from pathlib import Path

from app import __version__
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_deeplinks_slice() -> None:
    assert __version__ == "0.73.0"


def _create_component(client: TestClient, headers: dict[str, str], name: str) -> str:
    response = client.post(
        "/api/components",
        headers=headers,
        json={
            "component_type": "Server",
            "name": name,
            "hostname": f"{name}.example",
            "environment": "prod",
            "status": "active",
            "os_family": "linux",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["component_id"]


def test_incident_list_filters_by_component_id(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    ci_a = _create_component(client, auth_headers, "deeplink-ci-a")
    ci_b = _create_component(client, auth_headers, "deeplink-ci-b")

    for title, cid in (("INC for A", ci_a), ("INC for B", ci_b), ("INC none", None)):
        payload = {"title": title, "priority": "p3"}
        if cid:
            payload["ci_links"] = [{"component_id": cid}]
        created = client.post(
            "/api/itsm/incidents", headers=auth_headers, json=payload
        )
        assert created.status_code == 201, created.text

    filtered = client.get(
        f"/api/itsm/incidents?component_id={ci_a}",
        headers=auth_headers,
    )
    assert filtered.status_code == 200, filtered.text
    body = filtered.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "INC for A"
    assert body["items"][0]["ci_links"][0]["component_id"] == ci_a

    # Missing / unknown component_id → empty (not 500).
    empty = client.get(
        "/api/itsm/incidents?component_id=does-not-exist",
        headers=auth_headers,
    )
    assert empty.status_code == 200
    assert empty.json()["total"] == 0


def test_change_and_problem_list_filter_by_component_id(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    ci = _create_component(client, auth_headers, "deeplink-ci-chg")
    other = _create_component(client, auth_headers, "deeplink-ci-other")

    chg = client.post(
        "/api/itsm/changes",
        headers=auth_headers,
        json={
            "title": "CHG with CI",
            "change_type": "normal",
            "ci_links": [{"component_id": ci}],
        },
    )
    assert chg.status_code == 201, chg.text
    client.post(
        "/api/itsm/changes",
        headers=auth_headers,
        json={
            "title": "CHG other",
            "change_type": "normal",
            "ci_links": [{"component_id": other}],
        },
    )

    prb = client.post(
        "/api/itsm/problems",
        headers=auth_headers,
        json={
            "title": "PRB with CI",
            "ci_links": [{"component_id": ci}],
        },
    )
    assert prb.status_code == 201, prb.text

    chg_list = client.get(
        f"/api/itsm/changes?component_id={ci}", headers=auth_headers
    )
    assert chg_list.status_code == 200
    assert chg_list.json()["total"] == 1
    assert chg_list.json()["items"][0]["title"] == "CHG with CI"

    prb_list = client.get(
        f"/api/itsm/problems?component_id={ci}", headers=auth_headers
    )
    assert prb_list.status_code == 200
    assert prb_list.json()["total"] == 1
    assert prb_list.json()["items"][0]["title"] == "PRB with CI"


def test_dependency_bundle_404_safe_for_missing_ci(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    missing = client.get(
        "/api/dependencies/missing-ci-for-impact?depth=2",
        headers=auth_headers,
    )
    assert missing.status_code in (404, 400)


def test_frontend_deeplink_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.73.0"' in html
    assert 'id="itsmIncCiFilter"' in html
    assert 'id="itsmChgCiFilter"' in html
    assert 'id="itsmPrbCiFilter"' in html
    assert 'id="itsmIncImpactPanel"' in html
    assert 'id="itsmChgImpactPanel"' in html
    assert 'id="itsmPrbImpactPanel"' in html
    assert 'id="itsmCiPickerList"' in html
    assert 'id="btnComponentViewItsm"' in html
    assert "itsm/deeplinks.js?v=0.73.0" in html

    deeplinks = Path("frontend/static/js/itsm/deeplinks.js").read_text(encoding="utf-8")
    assert "openTicketsForComponent" in deeplinks
    assert "renderImpactPanel" in deeplinks

    cmdb = Path("frontend/static/js/cmdb.js").read_text(encoding="utf-8")
    assert "data-itsm=" in cmdb
    assert "openTicketsForComponent" in cmdb
