"""ITSM Change + Problem Management — CRUD, transitions, related links, create UX markers."""

from __future__ import annotations

from app import __version__
from app.db import get_database, get_itsm_database
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_change_problem_slice() -> None:
    assert __version__ == "0.81.0"


def _create_component(client: TestClient, headers: dict[str, str]) -> str:
    payload = {
        "component_type": "Server",
        "name": "itsm-chg-ci",
        "hostname": "itsm-chg-ci.example",
        "environment": "prod",
        "status": "active",
        "os_family": "linux",
    }
    response = client.post("/api/components", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["component_id"]


def test_change_crud_transition_activity_and_ci_link(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    component_id = _create_component(client, auth_headers)

    incident = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={"title": "Gateway 504 spike", "priority": "p2"},
    )
    assert incident.status_code == 201, incident.text
    incident_id = incident.json()["incident_id"]

    problem = client.post(
        "/api/itsm/problems",
        headers=auth_headers,
        json={"title": "Upstream timeout root cause", "priority": "p2"},
    )
    assert problem.status_code == 201, problem.text
    problem_id = problem.json()["problem_id"]

    created = client.post(
        "/api/itsm/changes",
        headers=auth_headers,
        json={
            "title": "Raise API gateway timeout",
            "description": "Increase upstream timeout to 30s",
            "justification": "Reduce 504s during peak",
            "change_type": "normal",
            "priority": "p2",
            "risk": "medium",
            "cab_required": True,
            "ci_links": [{"component_id": component_id}],
            "related_incident_ids": [incident_id],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["tenant_id"]
    assert body["change_id"].startswith("CHG-")
    assert body["number_display"].startswith("CHG-")
    assert body["status"] == "draft"
    assert body["change_type"] == "normal"
    assert body["cab_required"] is True
    assert body["ci_links"][0]["component_id"] == component_id
    assert body["related_incident_ids"] == [incident_id]

    change_id = body["change_id"]

    listed = client.get("/api/itsm/changes", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] >= 1

    got = client.get(f"/api/itsm/changes/{change_id}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["title"] == "Raise API gateway timeout"

    patched = client.patch(
        f"/api/itsm/changes/{change_id}",
        headers=auth_headers,
        json={"assignee_user_id": "chg.owner", "related_problem_ids": [problem_id]},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["assignee_user_id"] == "chg.owner"
    assert patched.json()["related_problem_ids"] == [problem_id]

    transitioned = client.post(
        f"/api/itsm/changes/{change_id}/transition",
        headers=auth_headers,
        json={"status": "submitted", "comment": "Ready for CAB"},
    )
    assert transitioned.status_code == 200, transitioned.text
    assert transitioned.json()["status"] == "submitted"

    bad = client.post(
        f"/api/itsm/changes/{change_id}/transition",
        headers=auth_headers,
        json={"status": "closed"},
    )
    assert bad.status_code == 409

    activities = client.get(
        f"/api/itsm/change/{change_id}/activities",
        headers=auth_headers,
    )
    assert activities.status_code == 200, activities.text
    types = {a["activity_type"] for a in activities.json()["items"]}
    assert "created" in types
    assert "status_change" in types

    comment = client.post(
        f"/api/itsm/change/{change_id}/activities",
        headers=auth_headers,
        json={"message": "CAB scheduled for Thursday", "activity_type": "comment"},
    )
    assert comment.status_code == 201, comment.text

    assert get_itsm_database()["itsm_changes"].count_documents({}) >= 1
    assert get_database()["itsm_changes"].count_documents({}) == 0


def test_problem_crud_transition_and_related_links(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    component_id = _create_component(client, auth_headers)

    incident = client.post(
        "/api/itsm/incidents",
        headers=auth_headers,
        json={"title": "Recurring billing 500", "priority": "p2"},
    )
    assert incident.status_code == 201, incident.text
    incident_id = incident.json()["incident_id"]

    created = client.post(
        "/api/itsm/problems",
        headers=auth_headers,
        json={
            "title": "Intermittent billing API failures",
            "description": "Errors correlate with cache misses",
            "priority": "p2",
            "category": "application",
            "workaround": "Retry with backoff",
            "known_error": True,
            "ci_links": [{"component_id": component_id}],
            "related_incident_ids": [incident_id],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["problem_id"].startswith("PRB-")
    assert body["number_display"].startswith("PRB-")
    assert body["status"] == "known_error"
    assert body["known_error"] is True
    assert body["related_incident_ids"] == [incident_id]
    assert body["ci_links"][0]["component_id"] == component_id

    problem_id = body["problem_id"]

    # Link incident back to the problem.
    linked = client.patch(
        f"/api/itsm/incidents/{incident_id}",
        headers=auth_headers,
        json={"problem_id": problem_id},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["problem_id"] == problem_id

    listed = client.get("/api/itsm/problems", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    transitioned = client.post(
        f"/api/itsm/problems/{problem_id}/transition",
        headers=auth_headers,
        json={"status": "resolved", "root_cause": "Stale Redis key TTL", "comment": "Fixed"},
    )
    assert transitioned.status_code == 200, transitioned.text
    assert transitioned.json()["status"] == "resolved"
    assert transitioned.json()["root_cause"] == "Stale Redis key TTL"

    bad = client.post(
        f"/api/itsm/problems/{problem_id}/transition",
        headers=auth_headers,
        json={"status": "new"},
    )
    assert bad.status_code == 409

    activities = client.get(
        f"/api/itsm/problem/{problem_id}/activities",
        headers=auth_headers,
    )
    assert activities.status_code == 200, activities.text
    assert any(a["activity_type"] == "created" for a in activities.json()["items"])

    assert get_itsm_database()["itsm_problems"].count_documents({}) >= 1
    assert get_database()["itsm_problems"].count_documents({}) == 0


def test_change_ci_link_rejects_missing_component(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post(
        "/api/itsm/changes",
        headers=auth_headers,
        json={
            "title": "Missing CI change",
            "ci_links": [{"component_id": "does-not-exist"}],
        },
    )
    assert created.status_code == 404


def test_cross_tenant_change_and_problem_are_404(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    chg = client.post(
        "/api/itsm/changes",
        headers=auth_headers,
        json={"title": "Tenant A change"},
    )
    assert chg.status_code == 201
    change_id = chg.json()["change_id"]

    prb = client.post(
        "/api/itsm/problems",
        headers=auth_headers,
        json={"title": "Tenant A problem"},
    )
    assert prb.status_code == 201
    problem_id = prb.json()["problem_id"]

    foreign_chg = dict(get_itsm_database()["itsm_changes"].find_one({"change_id": change_id}))
    foreign_chg.pop("_id", None)
    foreign_chg["tenant_id"] = "tenant-other-org"
    foreign_chg["change_id"] = "CHG-FOREIGN01"
    foreign_chg["number"] = 999001
    foreign_chg["number_display"] = "CHG-999001"
    get_itsm_database()["itsm_changes"].insert_one(foreign_chg)

    foreign_prb = dict(get_itsm_database()["itsm_problems"].find_one({"problem_id": problem_id}))
    foreign_prb.pop("_id", None)
    foreign_prb["tenant_id"] = "tenant-other-org"
    foreign_prb["problem_id"] = "PRB-FOREIGN01"
    foreign_prb["number"] = 999002
    foreign_prb["number_display"] = "PRB-999002"
    get_itsm_database()["itsm_problems"].insert_one(foreign_prb)

    assert client.get("/api/itsm/changes/CHG-FOREIGN01", headers=auth_headers).status_code == 404
    assert client.get("/api/itsm/problems/PRB-FOREIGN01", headers=auth_headers).status_code == 404
    assert client.get(f"/api/itsm/changes/{change_id}", headers=auth_headers).status_code == 200
    assert client.get(f"/api/itsm/problems/{problem_id}", headers=auth_headers).status_code == 200


def test_dashboard_includes_change_and_problem_counts(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    assert (
        client.post(
            "/api/itsm/changes",
            headers=auth_headers,
            json={"title": "Dash change"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/itsm/problems",
            headers=auth_headers,
            json={"title": "Dash problem"},
        ).status_code
        == 201
    )
    dash = client.get("/api/itsm/dashboard/summary", headers=auth_headers)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["open_changes"] >= 1
    assert body["open_problems"] >= 1


def test_frontend_change_problem_create_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.81.0"' in html
    assert 'data-tab="itsm-changes"' in html
    assert 'data-tab="itsm-problems"' in html
    assert 'id="btnNewItsmChg"' in html
    assert 'id="btnNewItsmPrb"' in html
    assert 'id="btnNewItsmInc"' in html
    assert 'id="itsmChangeModal"' in html
    assert 'id="itsmProblemModal"' in html
    assert 'id="itsmIncidentModal"' in html
    assert 'id="itsmChangeForm"' in html
    assert 'id="itsmProblemForm"' in html
    assert 'id="itsmIncidentForm"' in html
    assert "/static/js/itsm/changes.js" in html
    assert "/static/js/itsm/problems.js" in html
    assert "itsm-nav-stub" not in html
