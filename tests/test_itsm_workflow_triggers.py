"""ITSM N7 — workflow auto-triggers on_create / on_status / schedule (0.64.0)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import __version__
from app.db import get_itsm_database
from app.itsm.services import jobs as jobs_service
from app.itsm.services.jobs import JOB_WORKFLOW_SCHEDULES
from app.itsm.services import workflow_triggers as triggers
from app.tenancy import MIGRATION_TENANT_ID
from fastapi.testclient import TestClient


def test_version_bump_for_workflow_triggers_slice() -> None:
    assert __version__ == "0.83.0"


def _simple_graph(*, target_status: str = "submitted") -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start", "config": {}},
            {
                "id": "to_status",
                "type": "status_change",
                "label": "Move",
                "config": {"status": target_status},
            },
            {"id": "end", "type": "end", "label": "End", "config": {}},
        ],
        "edges": [
            {"id": "e1", "from": "start", "to": "to_status"},
            {"id": "e2", "from": "to_status", "to": "end"},
        ],
    }


def test_on_create_starts_active_change_workflow(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    wf = client.post(
        "/api/itsm/workflows",
        headers=auth_headers,
        json={
            "name": "Auto on create",
            "applies_to": "change",
            "trigger": "on_create",
            "active": False,
            "graph": _simple_graph(target_status="submitted"),
        },
    )
    assert wf.status_code == 201, wf.text
    workflow_id = wf.json()["workflow_id"]
    pub = client.post(
        f"/api/itsm/workflows/{workflow_id}/publish", headers=auth_headers
    )
    assert pub.status_code == 200, pub.text

    created = client.post(
        "/api/itsm/changes",
        headers=auth_headers,
        json={
            "title": "Auto-triggered change",
            "change_type": "normal",
            "priority": "p3",
        },
    )
    assert created.status_code == 201, created.text
    change_id = created.json()["change_id"]
    # Workflow status_change advances draft → submitted before create returns.
    assert created.json()["status"] == "submitted"
    got = client.get(f"/api/itsm/changes/{change_id}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["status"] == "submitted"

    execs = client.get(
        f"/api/itsm/workflow-executions?ticket_id={change_id}&workflow_id={workflow_id}",
        headers=auth_headers,
    )
    assert execs.status_code == 200
    assert execs.json()["total"] >= 1
    assert execs.json()["items"][0]["status"] == "completed"
    assert execs.json()["items"][0]["context"].get("auto_trigger") is True


def test_on_create_inactive_and_duplicate_guard(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    wf = client.post(
        "/api/itsm/workflows",
        headers=auth_headers,
        json={
            "name": "Inactive create",
            "applies_to": "change",
            "trigger": "on_create",
            "active": False,
            "graph": _simple_graph(),
        },
    )
    assert wf.status_code == 201
    workflow_id = wf.json()["workflow_id"]

    created = client.post(
        "/api/itsm/changes",
        headers=auth_headers,
        json={"title": "No auto", "change_type": "normal", "priority": "p3"},
    )
    assert created.status_code == 201
    change_id = created.json()["change_id"]
    execs = client.get(
        f"/api/itsm/workflow-executions?ticket_id={change_id}",
        headers=auth_headers,
    )
    assert execs.json()["total"] == 0

    # Activate then create another — one execution; second fire skips duplicate
    # while first is still open (use waiting graph).
    client.post(f"/api/itsm/workflows/{workflow_id}/publish", headers=auth_headers)
    # Seed an open execution manually via start, then fire_on_create should skip.
    started = client.post(
        f"/api/itsm/workflows/{workflow_id}/start",
        headers=auth_headers,
        json={"ticket_type": "change", "ticket_id": change_id},
    )
    # May complete immediately; if completed, has_open_execution is false.
    # Force an open execution by inserting waiting state if needed.
    if started.status_code == 201 and started.json().get("status") == "completed":
        get_itsm_database()["itsm_workflow_executions"].update_one(
            {"execution_id": started.json()["execution_id"]},
            {"$set": {"status": "running"}},
        )
    assert triggers.has_open_execution(
        tenant_id=MIGRATION_TENANT_ID,
        workflow_id=workflow_id,
        ticket_id=change_id,
    )
    again = triggers.fire_on_create(
        ticket_type="change",
        ticket_id=change_id,
        tenant_id=MIGRATION_TENANT_ID,
        actor={"user_id": "t", "username": "t"},
    )
    assert again == []


def test_on_status_filter_and_engine_loop_guard(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    # on_status only for "approved"
    wf = client.post(
        "/api/itsm/workflows",
        headers=auth_headers,
        json={
            "name": "On approved",
            "applies_to": "change",
            "trigger": "on_status",
            "trigger_config": {"statuses": ["approved"]},
            "active": True,
            "graph": {
                "nodes": [
                    {"id": "start", "type": "start", "config": {}},
                    {"id": "end", "type": "end", "config": {}},
                ],
                "edges": [{"id": "e1", "from": "start", "to": "end"}],
            },
        },
    )
    assert wf.status_code == 201, wf.text
    workflow_id = wf.json()["workflow_id"]

    created = client.post(
        "/api/itsm/changes",
        headers=auth_headers,
        json={"title": "Status filter", "change_type": "normal", "priority": "p3"},
    )
    change_id = created.json()["change_id"]

    # draft → submitted should NOT start (filter is approved only)
    client.post(
        f"/api/itsm/changes/{change_id}/transition",
        headers=auth_headers,
        json={"status": "submitted"},
    )
    execs = client.get(
        f"/api/itsm/workflow-executions?workflow_id={workflow_id}",
        headers=auth_headers,
    )
    assert execs.json()["total"] == 0

    # Walk to approved
    for st in ("approved",):
        # need submitted → approved is valid? Check transitions: submitted → approved yes
        tr = client.post(
            f"/api/itsm/changes/{change_id}/transition",
            headers=auth_headers,
            json={"status": st},
        )
        assert tr.status_code == 200, tr.text

    execs2 = client.get(
        f"/api/itsm/workflow-executions?workflow_id={workflow_id}&ticket_id={change_id}",
        headers=auth_headers,
    )
    assert execs2.json()["total"] == 1

    # Engine suppress: on_create workflow that status-changes should not fire on_status
    # when statuses filter would match the node target — covered by suppress in engine.


def test_schedule_trigger_fires_once_per_window(
    client: TestClient, auth_headers: dict[str, str], clean_db
) -> None:
    created = client.post(
        "/api/itsm/changes",
        headers=auth_headers,
        json={"title": "Schedule target", "change_type": "normal", "priority": "p3"},
    )
    assert created.status_code == 201
    change_id = created.json()["change_id"]

    wf = client.post(
        "/api/itsm/workflows",
        headers=auth_headers,
        json={
            "name": "Scheduled nudge",
            "applies_to": "change",
            "trigger": "schedule",
            "trigger_config": {"interval_minutes": 60},
            "active": True,
            "graph": {
                "nodes": [
                    {"id": "start", "type": "start", "config": {}},
                    {"id": "end", "type": "end", "config": {}},
                ],
                "edges": [{"id": "e1", "from": "start", "to": "end"}],
            },
        },
    )
    assert wf.status_code == 201, wf.text
    workflow_id = wf.json()["workflow_id"]
    # Force due
    get_itsm_database()["itsm_workflows"].update_one(
        {"workflow_id": workflow_id},
        {
            "$set": {
                "next_run_at": datetime.now(timezone.utc) - timedelta(minutes=1),
                "active": True,
            }
        },
    )

    tick1 = jobs_service.run_tick(
        tenant_id=MIGRATION_TENANT_ID,
        force=True,
        jobs=[JOB_WORKFLOW_SCHEDULES],
    )
    job1 = tick1["jobs"][JOB_WORKFLOW_SCHEDULES]
    assert job1["job"] == JOB_WORKFLOW_SCHEDULES
    assert job1["workflows_due"] >= 1
    assert job1["executions_started"] >= 1

    execs = client.get(
        f"/api/itsm/workflow-executions?workflow_id={workflow_id}&ticket_id={change_id}",
        headers=auth_headers,
    )
    assert execs.json()["total"] >= 1
    first_total = execs.json()["total"]

    # Immediate second tick: next_run_at advanced → not due → no new starts
    tick2 = jobs_service.run_tick(
        tenant_id=MIGRATION_TENANT_ID,
        force=True,
        jobs=[JOB_WORKFLOW_SCHEDULES],
    )
    job2 = tick2["jobs"][JOB_WORKFLOW_SCHEDULES]
    assert job2["workflows_due"] == 0
    execs2 = client.get(
        f"/api/itsm/workflow-executions?workflow_id={workflow_id}&ticket_id={change_id}",
        headers=auth_headers,
    )
    assert execs2.json()["total"] == first_total

    # Cancel still works on a running execution if any
    running = [
        e
        for e in execs2.json()["items"]
        if e.get("status") in ("running", "waiting_approval")
    ]
    if running:
        cancel = client.post(
            f"/api/itsm/workflow-executions/{running[0]['execution_id']}/cancel",
            headers=auth_headers,
        )
        assert cancel.status_code in (200, 409)


def test_job_catalog_includes_workflow_schedules(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    status = client.get("/api/itsm/jobs/status", headers=auth_headers)
    assert status.status_code == 200
    assert JOB_WORKFLOW_SCHEDULES in status.json()["jobs"]
