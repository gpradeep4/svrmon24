"""ITSM Approvals + Workflow engine/designer — functional coverage for 0.42.0."""

from __future__ import annotations

from app import __version__
from app.db import get_itsm_database
from fastapi.testclient import TestClient

from tests.frontend_paths import FRONTEND_INDEX


def test_version_bump_for_approvals_workflows_slice() -> None:
    assert __version__ == "0.94.0"


def _create_change(client: TestClient, headers: dict[str, str]) -> str:
    created = client.post(
        "/api/itsm/changes",
        headers=headers,
        json={
            "title": "WF change for approvals",
            "description": "Used by workflow tests",
            "change_type": "normal",
            "priority": "p3",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["change_id"]


def test_approval_crud_decide_and_activity(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    change_id = _create_change(client, auth_headers)

    created = client.post(
        "/api/itsm/approvals",
        headers=auth_headers,
        json={
            "title": "CAB approval",
            "ticket_type": "change",
            "ticket_id": change_id,
            "approver_user_ids": ["cab.lead"],
            "approver_group": "CAB",
            "description": "Please approve timeout change",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["approval_id"].startswith("APR-")
    assert body["status"] == "pending"
    assert body["ticket_id"] == change_id
    assert body["tenant_id"]
    approval_id = body["approval_id"]

    listed = client.get("/api/itsm/approvals?status=pending", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] >= 1

    got = client.get(f"/api/itsm/approvals/{approval_id}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["title"] == "CAB approval"

    patched = client.patch(
        f"/api/itsm/approvals/{approval_id}",
        headers=auth_headers,
        json={"policy": "cab-normal"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["policy"] == "cab-normal"

    decided = client.post(
        f"/api/itsm/approvals/{approval_id}/decide",
        headers=auth_headers,
        json={"decision": "approved", "comment": "Looks good"},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"
    assert decided.json()["comment"] == "Looks good"

    again = client.post(
        f"/api/itsm/approvals/{approval_id}/decide",
        headers=auth_headers,
        json={"decision": "rejected"},
    )
    assert again.status_code == 409

    activities = client.get(
        f"/api/itsm/change/{change_id}/activities",
        headers=auth_headers,
    )
    assert activities.status_code == 200, activities.text
    types = {a["activity_type"] for a in activities.json()["items"]}
    assert "approval" in types

    itsm = get_itsm_database()
    assert itsm is not None
    assert itsm["itsm_approvals"].count_documents({}) >= 1


def test_workflow_definition_execution_and_approval_gate(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    change_id = _create_change(client, auth_headers)

    graph = {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start", "config": {}, "x": 20, "y": 40},
            {
                "id": "submit",
                "type": "status_change",
                "label": "Submit",
                "config": {"status": "submitted"},
                "x": 160,
                "y": 40,
            },
            {
                "id": "cab",
                "type": "approval",
                "label": "CAB",
                "config": {"title": "CAB gate", "approver_user_ids": ["cab.lead"]},
                "x": 300,
                "y": 40,
            },
            {
                "id": "approve_chg",
                "type": "status_change",
                "label": "Mark approved",
                "config": {"status": "approved"},
                "x": 440,
                "y": 10,
            },
            {
                "id": "reject_chg",
                "type": "status_change",
                "label": "Mark rejected",
                "config": {"status": "rejected"},
                "x": 440,
                "y": 90,
            },
            {"id": "end_ok", "type": "end", "label": "Done", "config": {}, "x": 580, "y": 10},
            {"id": "end_no", "type": "end", "label": "Stopped", "config": {}, "x": 580, "y": 90},
        ],
        "edges": [
            {"id": "e1", "from": "start", "to": "submit"},
            {"id": "e2", "from": "submit", "to": "cab"},
            {"id": "e3", "from": "cab", "to": "approve_chg", "condition": "approved"},
            {"id": "e4", "from": "cab", "to": "reject_chg", "condition": "rejected"},
            {"id": "e5", "from": "approve_chg", "to": "end_ok"},
            {"id": "e6", "from": "reject_chg", "to": "end_no"},
        ],
    }

    created = client.post(
        "/api/itsm/workflows",
        headers=auth_headers,
        json={
            "name": "Normal change CAB flow",
            "description": "submit → CAB → approve/reject",
            "applies_to": "change",
            "trigger": "manual",
            "active": False,
            "graph": graph,
        },
    )
    assert created.status_code == 201, created.text
    wf = created.json()
    assert wf["workflow_id"].startswith("WF-")
    assert wf["version"] == 1
    assert wf["active"] is False
    workflow_id = wf["workflow_id"]

    listed = client.get("/api/itsm/workflows", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1

    # Inactive workflow cannot start.
    blocked = client.post(
        f"/api/itsm/workflows/{workflow_id}/start",
        headers=auth_headers,
        json={"ticket_type": "change", "ticket_id": change_id},
    )
    assert blocked.status_code == 409

    published = client.post(
        f"/api/itsm/workflows/{workflow_id}/publish",
        headers=auth_headers,
    )
    assert published.status_code == 200, published.text
    assert published.json()["active"] is True

    started = client.post(
        f"/api/itsm/workflows/{workflow_id}/start",
        headers=auth_headers,
        json={"ticket_type": "change", "ticket_id": change_id},
    )
    assert started.status_code == 201, started.text
    execution = started.json()
    assert execution["execution_id"].startswith("WX-")
    assert execution["status"] == "waiting_approval"
    assert execution["pending_approval_id"]
    assert execution["current_node_id"] == "cab"
    execution_id = execution["execution_id"]
    approval_id = execution["pending_approval_id"]

    # Ticket should already be submitted via status_change node.
    chg = client.get(f"/api/itsm/changes/{change_id}", headers=auth_headers)
    assert chg.status_code == 200
    assert chg.json()["status"] == "submitted"

    apr = client.get(f"/api/itsm/approvals/{approval_id}", headers=auth_headers)
    assert apr.status_code == 200
    assert apr.json()["workflow_execution_id"] == execution_id
    assert apr.json()["node_id"] == "cab"

    decided = client.post(
        f"/api/itsm/approvals/{approval_id}/decide",
        headers=auth_headers,
        json={"decision": "approved", "comment": "CAB ok"},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"

    ex = client.get(
        f"/api/itsm/workflow-executions/{execution_id}",
        headers=auth_headers,
    )
    assert ex.status_code == 200, ex.text
    body = ex.json()
    assert body["status"] == "completed"
    assert body["pending_approval_id"] is None
    assert any(h.get("action") == "waiting_approval" for h in body.get("history") or [])

    chg2 = client.get(f"/api/itsm/changes/{change_id}", headers=auth_headers)
    assert chg2.json()["status"] == "approved"

    exec_list = client.get(
        f"/api/itsm/workflow-executions?ticket_id={change_id}",
        headers=auth_headers,
    )
    assert exec_list.status_code == 200
    assert exec_list.json()["total"] >= 1

    deactivated = client.post(
        f"/api/itsm/workflows/{workflow_id}/activate",
        headers=auth_headers,
        json={"active": False},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["active"] is False


def test_workflow_graph_validation_rejects_bad_graph(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    bad = client.post(
        "/api/itsm/workflows",
        headers=auth_headers,
        json={
            "name": "Broken",
            "applies_to": "generic",
            "graph": {
                "nodes": [{"id": "only", "type": "end", "config": {}}],
                "edges": [],
            },
        },
    )
    assert bad.status_code == 400


def test_frontend_approvals_workflows_markers() -> None:
    html = FRONTEND_INDEX.read_text(encoding="utf-8")
    assert 'content="0.94.0"' in html
    assert 'data-tab="itsm-approvals"' in html
    assert 'data-tab="itsm-workflows"' in html
    assert 'id="tab-itsm-approvals"' in html
    assert 'id="tab-itsm-workflows"' in html
    assert 'id="itsmWfCanvas"' in html
    assert "itsm/approvals.js?v=0.94.0" in html
    assert "itsm/workflows.js?v=0.94.0" in html
    assert 'data-itsm-perm="itsm:approval:read"' in html
    assert 'data-itsm-perm="itsm:workflow:read"' in html
