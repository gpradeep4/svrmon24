"""Service Portal requests lifecycle (ITSM DB ``sp_requests``).

On submit, always creates an ITSM Change from the catalog item's
``change_type_key`` / ``itsm_change_type`` (OD-9) and moves the request to
``pending_approval``. Approval SoT remains ITSM Change (OD-2); SP4 syncs status.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...itsm.models.changes import ChangeCreate
from ...itsm.services import changes as changes_service
from ...itsm.services.changes import ChangeError
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from ..models.requests import (
    CANCELABLE_STATUSES,
    RequestCreate,
    RequestUpdate,
)
from . import catalog as catalog_service
from .catalog import CatalogError
from .form_validate import FormValidationError, validate_form_values
from .indexes import REQUESTS, ensure_portal_indexes

_RISK_TO_PRIORITY = {
    "high": "p2",
    "medium": "p3",
    "low": "p4",
}


class RequestError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        field_errors: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field_errors = field_errors


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_portal_indexes()
    return require_itsm_database()[REQUESTS]


def _new_request_id() -> str:
    return f"SPR-{uuid.uuid4().hex[:12].upper()}"


def _actor_name(actor: dict[str, Any] | None) -> str | None:
    actor = actor or {}
    return actor.get("user_id") or actor.get("username")


def _resolve_collect_mode(item: dict[str, Any], requested: str | None) -> str:
    allowed = list(item.get("allowed_collect_modes") or ["agentless"])
    mode = requested or item.get("default_collect_mode") or allowed[0]
    if mode not in allowed:
        raise RequestError(
            f"collect_mode '{mode}' not allowed for this item "
            f"(allowed: {', '.join(allowed)})"
        )
    return mode


def _resolve_placement(item: dict[str, Any], requested: str | None) -> str:
    item_placement = item.get("target_placement") or "either"
    if requested is None:
        return "on_prem" if item_placement == "either" else item_placement
    if item_placement != "either" and requested != item_placement:
        raise RequestError(
            f"target_placement '{requested}' not allowed "
            f"(item requires '{item_placement}')"
        )
    if requested not in ("on_prem", "cloud", "either"):
        raise RequestError(f"invalid target_placement '{requested}'")
    return requested


def _validate_form(item: dict[str, Any], form_values: dict[str, Any] | None) -> dict[str, Any]:
    try:
        return validate_form_values(item.get("form_schema") or {}, form_values)
    except FormValidationError as exc:
        raise RequestError(
            "form validation failed",
            status_code=400,
            field_errors=exc.field_errors,
        ) from exc


def _build_request_doc(
    *,
    item: dict[str, Any],
    payload: RequestCreate,
    tenant_id: str,
    actor: dict[str, Any] | None,
    form_values: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    now = _now()
    who = _actor_name(actor)
    collect_mode = _resolve_collect_mode(item, payload.collect_mode)
    placement = _resolve_placement(item, payload.target_placement)
    risk = item.get("risk_tier") or "medium"
    priority = payload.priority or _RISK_TO_PRIORITY.get(risk, "p3")
    doc = {
        "request_id": _new_request_id(),
        "item_id": item["item_id"],
        "item_key_snapshot": item.get("key"),
        "item_title_snapshot": item.get("title"),
        "domain": item.get("domain"),
        "action_key": item.get("action_key"),
        "change_type_key": item.get("change_type_key"),
        "itsm_change_type": item.get("itsm_change_type") or "normal",
        "risk_tier": risk,
        "target_placement": placement,
        "collect_mode": collect_mode,
        "component_id": payload.component_id,
        "component_snapshot": None,
        "form_values": form_values,
        "status": status,
        "change_id": None,
        "change_number_display": None,
        "change_status_snapshot": None,
        "linked_incident_id": payload.linked_incident_id,
        "requested_execution_mode": payload.requested_execution_mode,
        "cmdb_sync": item.get("cmdb_sync") or "none",
        "cmdb_sync_status": "pending" if item.get("cmdb_sync") in ("create", "update") else "none",
        "cmdb_sync_error": None,
        "priority": priority,
        "schema_version": item.get("schema_version") or 1,
        "created_at": now,
        "updated_at": now,
        "created_by": who,
        "updated_by": who,
        "submitted_at": None,
        "cancelled_at": None,
    }
    return stamp_tenant_id(doc, tenant_id=tid)


def create_request(
    payload: RequestCreate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    from ...services import entitlements as entitlements_service
    from ...services.entitlements import EntitlementError

    try:
        entitlements_service.assert_can_create_sp_request(tid)
    except EntitlementError as exc:
        raise RequestError(exc.message, status_code=exc.status_code) from exc
    try:
        item = catalog_service.get_catalog_item(
            tenant_id=tid, item_id=payload.item_id
        )
    except CatalogError as exc:
        raise RequestError(exc.message, status_code=exc.status_code) from exc
    if not item.get("enabled", True):
        raise RequestError("catalog item is disabled", status_code=400)

    form_values = _validate_form(item, payload.form_values)
    status = "draft"
    doc = _build_request_doc(
        item=item,
        payload=payload,
        tenant_id=tid,
        actor=actor,
        form_values=form_values,
        status=status,
    )
    _coll().insert_one(doc)
    serialized = serialize_document(doc)
    assert serialized is not None
    if payload.submit:
        return submit_request(
            serialized["request_id"], tenant_id=tid, actor=actor
        )
    return serialized


def get_request(*, tenant_id: str, request_id: str) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one(merge_tenant_filter({"request_id": request_id}, tid))
    if not doc:
        raise RequestError("request not found", status_code=404)
    return serialize_document(doc)  # type: ignore[return-value]


def list_requests(
    *,
    tenant_id: str,
    status: str | None = None,
    domain: str | None = None,
    created_by: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    clauses: list[dict[str, Any]] = []
    if status:
        clauses.append({"status": status})
    if domain:
        clauses.append({"domain": domain})
    if created_by:
        clauses.append({"created_by": created_by})
    base = {"$and": clauses} if clauses else None
    query = merge_tenant_filter(base, tid)
    coll = _coll()
    total = coll.count_documents(query)
    skip = max(0, (page - 1) * page_size)
    cursor = (
        coll.find(query)
        .sort([("updated_at", -1)])
        .skip(skip)
        .limit(page_size)
    )
    items = [serialize_document(doc) for doc in cursor]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def update_request(
    request_id: str,
    payload: RequestUpdate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = get_request(tenant_id=tid, request_id=request_id)
    if existing.get("status") != "draft":
        raise RequestError("only draft requests can be updated", status_code=409)

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return existing

    try:
        item = catalog_service.get_catalog_item(
            tenant_id=tid, item_id=existing["item_id"]
        )
    except CatalogError as exc:
        raise RequestError(exc.message, status_code=exc.status_code) from exc

    if "form_values" in updates:
        updates["form_values"] = _validate_form(item, updates["form_values"])
    if "collect_mode" in updates:
        updates["collect_mode"] = _resolve_collect_mode(
            item, updates["collect_mode"]
        )
    if "target_placement" in updates:
        updates["target_placement"] = _resolve_placement(
            item, updates["target_placement"]
        )

    updates["updated_at"] = _now()
    updates["updated_by"] = _actor_name(actor)
    result = _coll().find_one_and_update(
        merge_tenant_filter({"request_id": request_id}, tid),
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise RequestError("request not found", status_code=404)
    return serialize_document(result)  # type: ignore[return-value]


def submit_request(
    request_id: str,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate, create ITSM Change, move request → pending_approval."""
    tid = require_tenant_id(tenant_id)
    existing = get_request(tenant_id=tid, request_id=request_id)
    if existing.get("status") not in ("draft", "submitted"):
        raise RequestError(
            f"cannot submit request in status '{existing.get('status')}'",
            status_code=409,
        )
    if existing.get("change_id"):
        raise RequestError("request already has a linked Change", status_code=409)

    try:
        item = catalog_service.get_catalog_item(
            tenant_id=tid, item_id=existing["item_id"]
        )
    except CatalogError as exc:
        raise RequestError(exc.message, status_code=exc.status_code) from exc
    if not item.get("enabled", True):
        raise RequestError("catalog item is disabled", status_code=400)

    form_values = _validate_form(item, existing.get("form_values") or {})
    change_type = (item.get("itsm_change_type") or "normal").strip()
    if change_type not in ("standard", "normal", "emergency"):
        change_type = "normal"
    risk = item.get("risk_tier") or "medium"
    priority = existing.get("priority") or _RISK_TO_PRIORITY.get(risk, "p3")
    title = (
        f"[Service Portal] {item.get('title') or item.get('key')} "
        f"({existing['request_id']})"
    )
    description_parts = [
        f"Portal request `{existing['request_id']}`",
        f"Catalog item: {item.get('key')} ({item.get('item_id')})",
        f"Change type key: {item.get('change_type_key')}",
        f"Collect mode: {existing.get('collect_mode')}",
        f"Target placement: {existing.get('target_placement')}",
    ]
    if existing.get("component_id"):
        description_parts.append(f"Component: {existing['component_id']}")
    if existing.get("linked_incident_id"):
        description_parts.append(f"Linked incident: {existing['linked_incident_id']}")
    description_parts.append(f"Form values: {form_values!r}")

    related_incidents: list[str] = []
    if existing.get("linked_incident_id"):
        related_incidents.append(existing["linked_incident_id"])

    requester = _actor_name(actor) or existing.get("created_by")
    watchers = [requester] if requester else []

    change_payload = ChangeCreate(
        title=title[:500],
        description="\n".join(description_parts)[:20000],
        justification=f"Service Portal submit for {item.get('change_type_key')}",
        status="submitted",
        change_type=change_type,  # type: ignore[arg-type]
        risk=str(risk),
        priority=priority,  # type: ignore[arg-type]
        category="service_portal",
        subcategory=str(item.get("change_type_key") or "")[:128] or None,
        related_incident_ids=related_incidents,
        watcher_user_ids=watchers,
    )
    try:
        change = changes_service.create_change(
            change_payload, tenant_id=tid, actor=actor
        )
    except ChangeError as exc:
        raise RequestError(
            f"ITSM Change create failed: {exc.message}",
            status_code=getattr(exc, "status_code", 400) or 400,
        ) from exc

    now = _now()
    updates = {
        "form_values": form_values,
        "status": "pending_approval",
        "change_id": change.get("change_id"),
        "change_number_display": change.get("number_display"),
        "change_status_snapshot": change.get("status"),
        "change_type_key": item.get("change_type_key"),
        "itsm_change_type": change_type,
        "submitted_at": now,
        "updated_at": now,
        "updated_by": _actor_name(actor),
    }
    result = _coll().find_one_and_update(
        merge_tenant_filter({"request_id": request_id}, tid),
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise RequestError("request not found after submit", status_code=404)
    serialized = serialize_document(result)
    assert serialized is not None
    from . import audit as portal_audit
    from . import notifications as portal_notifications

    portal_notifications.notify_request_submitted(
        tenant_id=tid, request=serialized, actor=actor
    )
    portal_audit.record_portal_event(
        tenant_id=tid,
        action="portal.request.submit",
        actor=actor,
        request_id=serialized.get("request_id"),
        change_id=serialized.get("change_id"),
        resource_type="sp_request",
        resource_id=serialized.get("request_id"),
        details={
            "change_type_key": serialized.get("change_type_key"),
            "action_key": serialized.get("action_key"),
            "collect_mode": serialized.get("collect_mode"),
        },
    )
    return serialized


def cancel_request(
    request_id: str,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = get_request(tenant_id=tid, request_id=request_id)
    status = existing.get("status")
    if status not in CANCELABLE_STATUSES:
        raise RequestError(
            f"cannot cancel request in status '{status}'",
            status_code=409,
        )

    # Best-effort cancel linked Change when still cancellable.
    change_id = existing.get("change_id")
    change_status_snapshot = existing.get("change_status_snapshot")
    if change_id:
        try:
            from ...itsm.models.changes import ChangeTransition

            updated = changes_service.transition_change(
                change_id,
                ChangeTransition(status="cancelled", comment=comment or "Cancelled from Service Portal"),
                tenant_id=tid,
                actor=actor,
            )
            change_status_snapshot = updated.get("status")
        except ChangeError:
            # Leave portal cancel allowed even if Change already moved.
            chg = changes_service.get_change(change_id, tenant_id=tid)
            if chg:
                change_status_snapshot = chg.get("status")

    now = _now()
    result = _coll().find_one_and_update(
        merge_tenant_filter({"request_id": request_id}, tid),
        {
            "$set": {
                "status": "cancelled",
                "cancelled_at": now,
                "updated_at": now,
                "updated_by": _actor_name(actor),
                "change_status_snapshot": change_status_snapshot,
                "cancel_comment": (comment or "").strip() or None,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise RequestError("request not found", status_code=404)
    return serialize_document(result)  # type: ignore[return-value]


def link_incident(
    request_id: str,
    *,
    tenant_id: str,
    linked_incident_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach an optional ITSM incident id (SP8). Does not auto-approve."""
    tid = require_tenant_id(tenant_id)
    existing = get_request(tenant_id=tid, request_id=request_id)
    incident_id = (linked_incident_id or "").strip()
    if not incident_id:
        raise RequestError("linked_incident_id required", status_code=400)
    # Validate incident exists in-tenant when possible.
    try:
        from ...itsm.services import incidents as incidents_service

        inc = incidents_service.get_incident(incident_id, tenant_id=tid)
        if not inc:
            raise RequestError(
                f"incident '{incident_id}' not found", status_code=404
            )
    except RequestError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RequestError(
            f"incident lookup failed: {exc}", status_code=400
        ) from exc

    result = _coll().find_one_and_update(
        merge_tenant_filter({"request_id": request_id}, tid),
        {
            "$set": {
                "linked_incident_id": incident_id,
                "updated_at": _now(),
                "updated_by": _actor_name(actor),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise RequestError("request not found", status_code=404)

    # Best-effort: also attach to linked Change related_incident_ids.
    change_id = existing.get("change_id")
    if change_id:
        try:
            from ...itsm.models.changes import ChangeUpdate

            change = changes_service.get_change(change_id, tenant_id=tid) or {}
            related = list(change.get("related_incident_ids") or [])
            if incident_id not in related:
                related.append(incident_id)
                changes_service.update_change(
                    change_id,
                    ChangeUpdate(related_incident_ids=related),
                    tenant_id=tid,
                    actor=actor,
                )
        except Exception:  # noqa: BLE001
            pass

    from . import audit as portal_audit

    serialized = serialize_document(result)
    portal_audit.record_portal_event(
        tenant_id=tid,
        action="portal.request.link_incident",
        actor=actor,
        request_id=request_id,
        change_id=change_id,
        resource_type="sp_request",
        resource_id=request_id,
        details={"linked_incident_id": incident_id},
    )
    return serialized  # type: ignore[return-value]


def refresh_change_snapshot(
    request_id: str,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pull ITSM Change status and mirror request status (SP4 sync)."""
    from . import approvals as approvals_service
    from .approvals import ApprovalError

    try:
        return approvals_service.sync_request_from_change(
            request_id, tenant_id=tenant_id, actor=actor
        )
    except ApprovalError as exc:
        raise RequestError(exc.message, status_code=exc.status_code) from exc
