"""Validate related ticket id references within the same tenant."""

from __future__ import annotations

from typing import Any

from ...db import require_itsm_database
from ...tenancy import require_tenant_id
from .indexes import CHANGES, INCIDENTS, PROBLEMS, ensure_itsm_indexes


class RelatedTicketError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _exists(collection: str, *, tenant_id: str, id_field: str, value: str) -> bool:
    ensure_itsm_indexes()
    tid = require_tenant_id(tenant_id)
    key = (value or "").strip()
    if not key:
        return False
    return (
        require_itsm_database()[collection].find_one(
            {"tenant_id": tid, id_field: key}, {"_id": 1}
        )
        is not None
    )


def assert_incident_exists(*, tenant_id: str, incident_id: str) -> None:
    if not _exists(INCIDENTS, tenant_id=tenant_id, id_field="incident_id", value=incident_id):
        raise RelatedTicketError(
            f"Related incident '{incident_id}' not found in this tenant",
            status_code=400,
        )


def assert_change_exists(*, tenant_id: str, change_id: str) -> None:
    if not _exists(CHANGES, tenant_id=tenant_id, id_field="change_id", value=change_id):
        raise RelatedTicketError(
            f"Related change '{change_id}' not found in this tenant",
            status_code=400,
        )


def assert_problem_exists(*, tenant_id: str, problem_id: str) -> None:
    if not _exists(PROBLEMS, tenant_id=tenant_id, id_field="problem_id", value=problem_id):
        raise RelatedTicketError(
            f"Related problem '{problem_id}' not found in this tenant",
            status_code=400,
        )


def validate_related_refs(
    *,
    tenant_id: str,
    problem_id: str | None = None,
    change_id: str | None = None,
    related_incident_ids: list[str] | None = None,
    related_problem_ids: list[str] | None = None,
) -> None:
    """Raise RelatedTicketError when any provided id is missing for the tenant."""
    pid = (problem_id or "").strip() or None
    cid = (change_id or "").strip() or None
    if pid:
        assert_problem_exists(tenant_id=tenant_id, problem_id=pid)
    if cid:
        assert_change_exists(tenant_id=tenant_id, change_id=cid)
    for iid in related_incident_ids or []:
        item = str(iid or "").strip()
        if item:
            assert_incident_exists(tenant_id=tenant_id, incident_id=item)
    for prid in related_problem_ids or []:
        item = str(prid or "").strip()
        if item:
            assert_problem_exists(tenant_id=tenant_id, problem_id=item)


def resolve_related_summary(
    *,
    tenant_id: str,
    problem_id: str | None = None,
    change_id: str | None = None,
    related_incident_ids: list[str] | None = None,
    related_problem_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return click-through metadata for related ids (best-effort, no raise)."""
    tid = require_tenant_id(tenant_id)
    ensure_itsm_indexes()
    db = require_itsm_database()

    def _one(coll: str, id_field: str, value: str | None) -> dict[str, Any] | None:
        key = (value or "").strip()
        if not key:
            return None
        doc = db[coll].find_one(
            {"tenant_id": tid, id_field: key},
            {id_field: 1, "number_display": 1, "title": 1, "status": 1},
        )
        if not doc:
            return {"id": key, "found": False}
        return {
            "id": key,
            "found": True,
            "number_display": doc.get("number_display") or key,
            "title": doc.get("title"),
            "status": doc.get("status"),
        }

    incidents = [
        _one(INCIDENTS, "incident_id", str(x))
        for x in (related_incident_ids or [])
        if str(x or "").strip()
    ]
    problems = [
        _one(PROBLEMS, "problem_id", str(x))
        for x in (related_problem_ids or [])
        if str(x or "").strip()
    ]
    return {
        "problem": _one(PROBLEMS, "problem_id", problem_id),
        "change": _one(CHANGES, "change_id", change_id),
        "related_incidents": [x for x in incidents if x],
        "related_problems": [x for x in problems if x],
    }
