"""Workflow execution engine — start / advance / resume after approval."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from ..models.approvals import ApprovalCreate
from ..models.changes import ChangeTransition
from ..models.common import TICKET_TYPES
from ..models.incidents import IncidentTransition
from ..models.problems import ProblemTransition
from ..models.workflows import EXECUTION_STATUSES
from . import activities as activities_service
from . import approvals as approvals_service
from . import changes as changes_service
from . import incidents as incidents_service
from . import problems as problems_service
from . import workflows as workflows_service
from .indexes import WORKFLOW_EXECUTIONS, ensure_itsm_indexes
from .workflows import WorkflowError


class ExecutionError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _exec_coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[WORKFLOW_EXECUTIONS]


def _new_execution_id() -> str:
    return f"WX-{uuid.uuid4().hex[:10].upper()}"


def _actor_fields(actor: dict[str, Any] | None) -> dict[str, str | None]:
    actor = actor or {}
    return {
        "user_id": actor.get("user_id") or actor.get("username"),
        "username": actor.get("username") or actor.get("user_id"),
    }


def _history_entry(
    *,
    node_id: str,
    node_type: str,
    action: str,
    detail: str | None = None,
    branch: str | None = None,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    who = _actor_fields(actor)
    return {
        "at": _now().isoformat(),
        "node_id": node_id,
        "node_type": node_type,
        "action": action,
        "detail": detail,
        "branch": branch,
        "actor_username": who["username"],
    }


def _nodes_by_id(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(n["id"]): n for n in (graph.get("nodes") or [])}


def _find_start(graph: dict[str, Any]) -> dict[str, Any]:
    for node in graph.get("nodes") or []:
        if node.get("type") == "start":
            return node
    raise ExecutionError("Workflow has no start node")


def _next_node_id(
    graph: dict[str, Any],
    from_id: str,
    *,
    branch: str | None = None,
) -> str | None:
    edges = [e for e in (graph.get("edges") or []) if e.get("from") == from_id]
    if not edges:
        return None
    if branch:
        for edge in edges:
            if edge.get("condition") == branch:
                return edge.get("to")
    # Prefer unconditional edge.
    for edge in edges:
        if not edge.get("condition"):
            return edge.get("to")
    # Fallback: first edge.
    return edges[0].get("to")


def _ensure_ticket(ticket_type: str, ticket_id: str, *, tenant_id: str) -> dict[str, Any]:
    try:
        return approvals_service.ensure_ticket_exists(
            ticket_type, ticket_id, tenant_id=tenant_id
        )
    except approvals_service.ApprovalError as exc:
        raise ExecutionError(exc.message, status_code=exc.status_code) from exc


def _apply_status_change(
    *,
    ticket_type: str,
    ticket_id: str,
    status: str,
    tenant_id: str,
    actor: dict[str, Any] | None,
) -> None:
    from .workflow_triggers import suppress_auto_triggers

    # Engine-driven transitions must not re-fire on_status auto-triggers (loop guard).
    with suppress_auto_triggers():
        if ticket_type == "incident":
            incidents_service.transition_incident(
                ticket_id,
                IncidentTransition(status=status),  # type: ignore[arg-type]
                tenant_id=tenant_id,
                actor=actor,
            )
        elif ticket_type == "change":
            changes_service.transition_change(
                ticket_id,
                ChangeTransition(status=status),  # type: ignore[arg-type]
                tenant_id=tenant_id,
                actor=actor,
            )
        elif ticket_type == "problem":
            problems_service.transition_problem(
                ticket_id,
                ProblemTransition(status=status),  # type: ignore[arg-type]
                tenant_id=tenant_id,
                actor=actor,
            )
        else:
            raise ExecutionError(f"Unsupported ticket_type '{ticket_type}'")


def get_execution(execution_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _exec_coll().find_one({"tenant_id": tid, "execution_id": execution_id})
    return serialize_document(doc)


def list_executions(
    *,
    tenant_id: str,
    workflow_id: str | None = None,
    ticket_type: str | None = None,
    ticket_id: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    clauses: list[dict[str, Any]] = []
    if workflow_id:
        clauses.append({"workflow_id": workflow_id.strip()})
    if ticket_type:
        if ticket_type not in TICKET_TYPES:
            raise ExecutionError(f"Invalid ticket_type '{ticket_type}'")
        clauses.append({"ticket_type": ticket_type})
    if ticket_id:
        clauses.append({"ticket_id": ticket_id.strip()})
    if status:
        if status not in EXECUTION_STATUSES:
            raise ExecutionError(f"Invalid status '{status}'")
        clauses.append({"status": status})

    query: dict[str, Any] = {"tenant_id": tid}
    if clauses:
        query = merge_tenant_filter({"$and": clauses}, tid)

    allowed_sort = {"updated_at", "created_at", "status", "workflow_id"}
    if sort_by not in allowed_sort:
        sort_by = "updated_at"
    direction = DESCENDING if str(sort_dir).lower() != "asc" else ASCENDING

    coll = _exec_coll()
    total = coll.count_documents(query)
    cursor = (
        coll.find(query)
        .sort([(sort_by, direction)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "tenant_id": tid,
    }


def start_execution(
    workflow_id: str,
    *,
    ticket_type: str,
    ticket_id: str,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if ticket_type not in TICKET_TYPES:
        raise ExecutionError(f"Invalid ticket_type '{ticket_type}'")

    workflow = workflows_service.get_workflow(workflow_id, tenant_id=tid)
    if workflow is None:
        raise ExecutionError(f"Workflow '{workflow_id}' not found", status_code=404)
    if not workflow.get("active"):
        raise ExecutionError(
            f"Workflow '{workflow_id}' is not active",
            status_code=409,
        )
    applies = workflow.get("applies_to")
    if applies not in (None, "generic", ticket_type):
        raise ExecutionError(
            f"Workflow applies_to '{applies}' does not match ticket_type '{ticket_type}'",
            status_code=409,
        )

    _ensure_ticket(ticket_type, ticket_id, tenant_id=tid)
    graph = workflow.get("graph") or {}
    try:
        workflows_service.validate_graph(graph)
    except WorkflowError as exc:
        raise ExecutionError(exc.message, status_code=exc.status_code) from exc

    start = _find_start(graph)
    who = _actor_fields(actor)
    now = _now()
    execution_id = _new_execution_id()
    history = [
        _history_entry(
            node_id=str(start["id"]),
            node_type="start",
            action="entered",
            detail="Execution started",
            actor=actor,
        )
    ]
    doc: dict[str, Any] = {
        "execution_id": execution_id,
        "workflow_id": workflow_id,
        "workflow_version": int(workflow.get("version") or 1),
        "workflow_name": workflow.get("name"),
        "ticket_type": ticket_type,
        "ticket_id": ticket_id.strip(),
        "status": "running",
        "current_node_id": str(start["id"]),
        "context": context or {},
        "history": history,
        "error": None,
        "pending_approval_id": None,
        "graph_snapshot": graph,
        "created_at": now,
        "updated_at": now,
        "created_by": who["username"],
        "updated_by": who["username"],
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _exec_coll().insert_one(doc)

    activities_service.append_activity(
        tenant_id=tid,
        ticket_type=ticket_type,
        ticket_id=ticket_id.strip(),
        activity_type="workflow",
        message=f"Workflow started: {workflow.get('name')} ({execution_id})",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        to_value="running",
    )

    # Auto-advance past start into the first real step.
    return advance_execution(execution_id, tenant_id=tid, actor=actor)


def _persist(execution_id: str, *, tenant_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    updates = {**updates, "updated_at": _now()}
    doc = _exec_coll().find_one_and_update(
        {"tenant_id": tenant_id, "execution_id": execution_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise ExecutionError(f"Execution '{execution_id}' not found", status_code=404)
    return serialize_document(doc)  # type: ignore[return-value]


def advance_execution(
    execution_id: str,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
    branch: str | None = None,
    comment: str | None = None,
    max_steps: int = 20,
) -> dict[str, Any]:
    """Advance the execution until waiting, completed, failed, or max_steps."""
    tid = require_tenant_id(tenant_id)
    doc = _exec_coll().find_one({"tenant_id": tid, "execution_id": execution_id})
    if doc is None:
        raise ExecutionError(f"Execution '{execution_id}' not found", status_code=404)

    status = str(doc.get("status") or "")
    if status in {"completed", "failed", "cancelled"}:
        raise ExecutionError(
            f"Execution is already '{status}'",
            status_code=409,
        )
    if status == "waiting_approval" and not branch:
        raise ExecutionError(
            "Execution is waiting on approval; decide the approval to resume",
            status_code=409,
        )

    graph = doc.get("graph_snapshot") or {}
    by_id = _nodes_by_id(graph)
    history: list[dict[str, Any]] = list(doc.get("history") or [])
    current_id = str(doc.get("current_node_id") or "")
    who = _actor_fields(actor)
    ticket_type = str(doc["ticket_type"])
    ticket_id = str(doc["ticket_id"])
    pending_approval_id = doc.get("pending_approval_id")
    context = dict(doc.get("context") or {})

    # If resuming with a branch from waiting_approval, leave current approval node.
    if status == "waiting_approval" and branch:
        node = by_id.get(current_id) or {}
        history.append(
            _history_entry(
                node_id=current_id,
                node_type=str(node.get("type") or "approval"),
                action="resumed",
                detail=comment or f"Approval decision: {branch}",
                branch=branch,
                actor=actor,
            )
        )
        next_id = _next_node_id(graph, current_id, branch=branch)
        if not next_id:
            return _persist(
                execution_id,
                tenant_id=tid,
                updates={
                    "status": "failed",
                    "error": f"No edge for branch '{branch}' from node '{current_id}'",
                    "history": history,
                    "pending_approval_id": None,
                    "updated_by": who["username"],
                },
            )
        current_id = next_id
        pending_approval_id = None
        status = "running"

    steps = 0
    while steps < max_steps:
        steps += 1
        node = by_id.get(current_id)
        if node is None:
            return _persist(
                execution_id,
                tenant_id=tid,
                updates={
                    "status": "failed",
                    "error": f"Unknown node '{current_id}'",
                    "current_node_id": current_id,
                    "history": history,
                    "updated_by": who["username"],
                },
            )

        ntype = str(node.get("type") or "")
        history.append(
            _history_entry(
                node_id=current_id,
                node_type=ntype,
                action="entered",
                actor=actor,
            )
        )

        if ntype == "start":
            next_id = _next_node_id(graph, current_id)
            if not next_id:
                return _persist(
                    execution_id,
                    tenant_id=tid,
                    updates={
                        "status": "failed",
                        "error": "Start node has no outgoing edge",
                        "current_node_id": current_id,
                        "history": history,
                        "updated_by": who["username"],
                    },
                )
            current_id = next_id
            continue

        if ntype == "end":
            history.append(
                _history_entry(
                    node_id=current_id,
                    node_type="end",
                    action="completed",
                    detail="Workflow finished",
                    actor=actor,
                )
            )
            result = _persist(
                execution_id,
                tenant_id=tid,
                updates={
                    "status": "completed",
                    "current_node_id": current_id,
                    "history": history,
                    "error": None,
                    "pending_approval_id": None,
                    "context": context,
                    "updated_by": who["username"],
                },
            )
            activities_service.append_activity(
                tenant_id=tid,
                ticket_type=ticket_type,
                ticket_id=ticket_id,
                activity_type="workflow",
                message=f"Workflow completed ({execution_id})",
                actor_user_id=who["user_id"],
                actor_username=who["username"],
                to_value="completed",
            )
            return result

        if ntype == "status_change":
            target_status = str((node.get("config") or {}).get("status") or "").strip()
            try:
                _apply_status_change(
                    ticket_type=ticket_type,
                    ticket_id=ticket_id,
                    status=target_status,
                    tenant_id=tid,
                    actor=actor,
                )
                history.append(
                    _history_entry(
                        node_id=current_id,
                        node_type=ntype,
                        action="status_changed",
                        detail=f"Status → {target_status}",
                        actor=actor,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                history.append(
                    _history_entry(
                        node_id=current_id,
                        node_type=ntype,
                        action="error",
                        detail=str(exc),
                        actor=actor,
                    )
                )
                return _persist(
                    execution_id,
                    tenant_id=tid,
                    updates={
                        "status": "failed",
                        "error": str(exc),
                        "current_node_id": current_id,
                        "history": history,
                        "updated_by": who["username"],
                    },
                )
            next_id = _next_node_id(graph, current_id)
            if not next_id:
                return _persist(
                    execution_id,
                    tenant_id=tid,
                    updates={
                        "status": "failed",
                        "error": f"status_change node '{current_id}' has no outgoing edge",
                        "current_node_id": current_id,
                        "history": history,
                        "updated_by": who["username"],
                    },
                )
            current_id = next_id
            continue

        if ntype == "approval":
            cfg = node.get("config") or {}
            title = (
                str(cfg.get("title") or node.get("label") or "Workflow approval")
            ).strip()
            try:
                approval = approvals_service.create_approval(
                    ApprovalCreate(
                        title=title,
                        ticket_type=ticket_type,  # type: ignore[arg-type]
                        ticket_id=ticket_id,
                        description=str(cfg.get("description") or "") or None,
                        approver_user_ids=list(cfg.get("approver_user_ids") or []),
                        approver_group=(cfg.get("approver_group") or None),
                        policy=(cfg.get("policy") or None),
                        workflow_execution_id=execution_id,
                        node_id=current_id,
                    ),
                    tenant_id=tid,
                    actor=actor,
                    skip_ticket_check=True,
                )
            except Exception as exc:  # noqa: BLE001
                history.append(
                    _history_entry(
                        node_id=current_id,
                        node_type=ntype,
                        action="error",
                        detail=str(exc),
                        actor=actor,
                    )
                )
                return _persist(
                    execution_id,
                    tenant_id=tid,
                    updates={
                        "status": "failed",
                        "error": str(exc),
                        "current_node_id": current_id,
                        "history": history,
                        "updated_by": who["username"],
                    },
                )

            pending_approval_id = approval.get("approval_id")
            history.append(
                _history_entry(
                    node_id=current_id,
                    node_type=ntype,
                    action="waiting_approval",
                    detail=f"Created approval {pending_approval_id}",
                    actor=actor,
                )
            )
            return _persist(
                execution_id,
                tenant_id=tid,
                updates={
                    "status": "waiting_approval",
                    "current_node_id": current_id,
                    "history": history,
                    "pending_approval_id": pending_approval_id,
                    "context": context,
                    "error": None,
                    "updated_by": who["username"],
                },
            )

        return _persist(
            execution_id,
            tenant_id=tid,
            updates={
                "status": "failed",
                "error": f"Unsupported node type '{ntype}'",
                "current_node_id": current_id,
                "history": history,
                "updated_by": who["username"],
            },
        )

    return _persist(
        execution_id,
        tenant_id=tid,
        updates={
            "status": "running",
            "current_node_id": current_id,
            "history": history,
            "context": context,
            "pending_approval_id": pending_approval_id,
            "error": "Paused after max auto-advance steps",
            "updated_by": who["username"],
        },
    )


def resume_after_approval(
    *,
    execution_id: str,
    approval_id: str,
    decision: str,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    doc = _exec_coll().find_one({"tenant_id": tid, "execution_id": execution_id})
    if doc is None:
        raise ExecutionError(f"Execution '{execution_id}' not found", status_code=404)
    if doc.get("status") != "waiting_approval":
        raise ExecutionError(
            f"Execution is not waiting_approval (status={doc.get('status')})",
            status_code=409,
        )
    if doc.get("pending_approval_id") and doc.get("pending_approval_id") != approval_id:
        raise ExecutionError(
            "Approval id does not match pending approval on execution",
            status_code=409,
        )
    branch = "approved" if decision == "approved" else "rejected"
    return advance_execution(
        execution_id,
        tenant_id=tid,
        actor=actor,
        branch=branch,
        comment=f"Approval {approval_id} → {decision}",
    )


def cancel_execution(
    execution_id: str,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    doc = _exec_coll().find_one({"tenant_id": tid, "execution_id": execution_id})
    if doc is None:
        raise ExecutionError(f"Execution '{execution_id}' not found", status_code=404)
    if doc.get("status") in {"completed", "cancelled"}:
        raise ExecutionError(
            f"Cannot cancel execution in status '{doc.get('status')}'",
            status_code=409,
        )
    who = _actor_fields(actor)
    history = list(doc.get("history") or [])
    history.append(
        _history_entry(
            node_id=str(doc.get("current_node_id") or ""),
            node_type="system",
            action="cancelled",
            detail=comment or "Execution cancelled",
            actor=actor,
        )
    )
    # Cancel pending approval if any.
    pending = doc.get("pending_approval_id")
    if pending:
        try:
            approvals_service.cancel_approval(
                str(pending),
                tenant_id=tid,
                actor=actor,
                comment="Cancelled with workflow execution",
            )
        except Exception:  # noqa: BLE001
            pass

    result = _persist(
        execution_id,
        tenant_id=tid,
        updates={
            "status": "cancelled",
            "history": history,
            "pending_approval_id": None,
            "updated_by": who["username"],
            "error": comment,
        },
    )
    activities_service.append_activity(
        tenant_id=tid,
        ticket_type=str(doc["ticket_type"]),
        ticket_id=str(doc["ticket_id"]),
        activity_type="workflow",
        message=f"Workflow cancelled ({execution_id})",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        to_value="cancelled",
    )
    return result
