"""Workflow definition CRUD — ITSM DB only."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from ..models.workflows import (
    WORKFLOW_APPLIES_TO,
    WORKFLOW_NODE_TYPES,
    WORKFLOW_TRIGGERS,
    WorkflowCreate,
    WorkflowGraph,
    WorkflowUpdate,
)
from .indexes import WORKFLOWS, ensure_itsm_indexes


class WorkflowError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[WORKFLOWS]


def _new_workflow_id() -> str:
    return f"WF-{uuid.uuid4().hex[:10].upper()}"


def _actor_fields(actor: dict[str, Any] | None) -> dict[str, str | None]:
    actor = actor or {}
    return {
        "user_id": actor.get("user_id") or actor.get("username"),
        "username": actor.get("username") or actor.get("user_id"),
    }


def validate_graph(graph: WorkflowGraph | dict[str, Any]) -> dict[str, Any]:
    """Validate nodes/edges; return serializable graph dict."""
    if isinstance(graph, WorkflowGraph):
        data = graph.model_dump(by_alias=True)
    else:
        data = WorkflowGraph.model_validate(graph).model_dump(by_alias=True)

    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    if not nodes:
        raise WorkflowError("Workflow graph must include at least one node")

    ids: set[str] = set()
    start_count = 0
    end_count = 0
    for node in nodes:
        nid = str(node.get("id") or "").strip()
        ntype = str(node.get("type") or "").strip()
        if not nid:
            raise WorkflowError("Each node requires an id")
        if nid in ids:
            raise WorkflowError(f"Duplicate node id '{nid}'")
        if ntype not in WORKFLOW_NODE_TYPES:
            raise WorkflowError(f"Invalid node type '{ntype}'")
        ids.add(nid)
        if ntype == "start":
            start_count += 1
        if ntype == "end":
            end_count += 1
        if ntype == "status_change":
            status = (node.get("config") or {}).get("status")
            if not status:
                raise WorkflowError(
                    f"status_change node '{nid}' requires config.status"
                )
        if ntype == "approval":
            cfg = node.get("config") or {}
            title = (cfg.get("title") or node.get("label") or "").strip()
            if not title:
                raise WorkflowError(
                    f"approval node '{nid}' requires config.title or label"
                )

    if start_count != 1:
        raise WorkflowError("Workflow graph must have exactly one start node")
    if end_count < 1:
        raise WorkflowError("Workflow graph must have at least one end node")

    for edge in edges:
        frm = str(edge.get("from") or "").strip()
        to = str(edge.get("to") or "").strip()
        if frm not in ids or to not in ids:
            raise WorkflowError(f"Edge references unknown node ('{frm}' → '{to}')")
        if not edge.get("id"):
            edge["id"] = f"e-{frm}-{to}"

    return {"nodes": nodes, "edges": edges}


def get_workflow(workflow_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one({"tenant_id": tid, "workflow_id": workflow_id})
    return serialize_document(doc)


def list_workflows(
    *,
    tenant_id: str,
    q: str | None = None,
    applies_to: str | None = None,
    active: bool | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    clauses: list[dict[str, Any]] = []
    if applies_to:
        if applies_to not in WORKFLOW_APPLIES_TO:
            raise WorkflowError(f"Invalid applies_to '{applies_to}'")
        clauses.append({"applies_to": applies_to})
    if active is not None:
        clauses.append({"active": bool(active)})
    if q and q.strip():
        term = q.strip()
        clauses.append(
            {
                "$or": [
                    {"name": {"$regex": term, "$options": "i"}},
                    {"workflow_id": {"$regex": term, "$options": "i"}},
                    {"description": {"$regex": term, "$options": "i"}},
                ]
            }
        )

    query: dict[str, Any] = {"tenant_id": tid}
    if clauses:
        query = merge_tenant_filter({"$and": clauses}, tid)

    allowed_sort = {"updated_at", "created_at", "name", "version", "active"}
    if sort_by not in allowed_sort:
        sort_by = "updated_at"
    direction = DESCENDING if str(sort_dir).lower() != "asc" else ASCENDING

    coll = _coll()
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


def create_workflow(
    payload: WorkflowCreate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if payload.applies_to not in WORKFLOW_APPLIES_TO:
        raise WorkflowError(f"Invalid applies_to '{payload.applies_to}'")
    if payload.trigger not in WORKFLOW_TRIGGERS:
        raise WorkflowError(f"Invalid trigger '{payload.trigger}'")

    graph = validate_graph(payload.graph)
    who = _actor_fields(actor)
    now = _now()
    workflow_id = _new_workflow_id()
    doc: dict[str, Any] = {
        "workflow_id": workflow_id,
        "name": payload.name.strip(),
        "description": (payload.description or "").strip() or None,
        "version": 1,
        "active": bool(payload.active),
        "applies_to": payload.applies_to,
        "trigger": payload.trigger,
        "trigger_config": payload.trigger_config or {},
        "graph": graph,
        "variables_schema": payload.variables_schema,
        "created_at": now,
        "updated_at": now,
        "created_by": who["username"],
        "updated_by": who["username"],
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _coll().insert_one(doc)
    return serialize_document(doc)  # type: ignore[return-value]


def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
    bump_version: bool = True,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "workflow_id": workflow_id})
    if existing is None:
        raise WorkflowError(f"Workflow '{workflow_id}' not found", status_code=404)

    updates = payload.model_dump(exclude_unset=True, by_alias=True)
    if not updates:
        return serialize_document(existing)  # type: ignore[return-value]

    if "applies_to" in updates and updates["applies_to"] not in WORKFLOW_APPLIES_TO:
        raise WorkflowError(f"Invalid applies_to '{updates['applies_to']}'")
    if "trigger" in updates and updates["trigger"] not in WORKFLOW_TRIGGERS:
        raise WorkflowError(f"Invalid trigger '{updates['trigger']}'")
    if "name" in updates and updates["name"] is not None:
        updates["name"] = updates["name"].strip()
    if "description" in updates and updates["description"] is not None:
        updates["description"] = updates["description"].strip() or None
    if "graph" in updates and updates["graph"] is not None:
        updates["graph"] = validate_graph(updates["graph"])
        if bump_version:
            updates["version"] = int(existing.get("version") or 1) + 1

    who = _actor_fields(actor)
    updates["updated_at"] = _now()
    updates["updated_by"] = who["username"]

    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "workflow_id": workflow_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise WorkflowError(f"Workflow '{workflow_id}' not found", status_code=404)
    return serialize_document(doc)  # type: ignore[return-value]


def set_workflow_active(
    workflow_id: str,
    *,
    active: bool,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "workflow_id": workflow_id})
    if existing is None:
        raise WorkflowError(f"Workflow '{workflow_id}' not found", status_code=404)
    # Re-validate graph before activating.
    if active:
        validate_graph(existing.get("graph") or {"nodes": [], "edges": []})

    who = _actor_fields(actor)
    updates: dict[str, Any] = {
        "active": bool(active),
        "updated_at": _now(),
        "updated_by": who["username"],
    }
    # Seed schedule window when activating a schedule trigger.
    if active and existing.get("trigger") == "schedule" and not existing.get("next_run_at"):
        updates["next_run_at"] = _now()

    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "workflow_id": workflow_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise WorkflowError(f"Workflow '{workflow_id}' not found", status_code=404)
    return serialize_document(doc)  # type: ignore[return-value]


def publish_workflow(
    workflow_id: str,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish = validate + activate (alias for activate with validation)."""
    return set_workflow_active(
        workflow_id, active=True, tenant_id=tenant_id, actor=actor
    )
