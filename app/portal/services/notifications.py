"""Service Portal notification helpers — reuse ITSM in-app emit (SP5).

Deep-links: notifications carry ``portal_request_id`` plus Change
``ticket_type``/``ticket_id`` so the inbox can open Portal or ITSM.
"""

from __future__ import annotations

from typing import Any

from ...itsm.services import notifications as itsm_notifications


def _recipient_from_request(request: dict[str, Any]) -> list[str]:
    who = request.get("created_by") or request.get("updated_by")
    if not who:
        return []
    return [str(who)]


def notify_request_submitted(
    *,
    tenant_id: str,
    request: dict[str, Any],
    actor: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Confirm to requester that Change was created and awaits approval."""
    recipients = _recipient_from_request(request)
    if not recipients:
        return []
    change_id = request.get("change_id") or ""
    change_label = request.get("change_number_display") or change_id or "Change"
    request_id = request.get("request_id") or ""
    title = request.get("item_title_snapshot") or request.get("item_key_snapshot") or "request"
    return itsm_notifications.emit_best_effort(
        tenant_id=tenant_id,
        event_type="status_change",
        recipient_user_ids=recipients,
        subject=f"Portal request submitted: {title}",
        body=(
            f"Service Portal request {request_id} was submitted. "
            f"ITSM {change_label} is awaiting approval. "
            f"Decide in ITSM Changes/Approvals; Portal mirrors status."
        ),
        ticket_type="change",
        ticket_id=change_id or None,
        portal_request_id=request_id or None,
        actor=actor,
        exclude_actor=False,
    )


def notify_request_decision(
    *,
    tenant_id: str,
    request: dict[str, Any],
    decision: str,
    actor: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Notify requester when linked Change decision is mirrored to the request."""
    recipients = _recipient_from_request(request)
    if not recipients:
        return []
    change_id = request.get("change_id") or ""
    change_label = request.get("change_number_display") or change_id or "Change"
    request_id = request.get("request_id") or ""
    title = request.get("item_title_snapshot") or request.get("item_key_snapshot") or "request"
    decision_clean = (decision or "").strip().lower() or "updated"
    return itsm_notifications.emit_best_effort(
        tenant_id=tenant_id,
        event_type="approval_decided" if decision_clean in ("approved", "rejected") else "status_change",
        recipient_user_ids=recipients,
        subject=f"Portal request {decision_clean}: {title}",
        body=(
            f"Service Portal request {request_id} is now {decision_clean} "
            f"(ITSM {change_label} status: {request.get('change_status_snapshot') or decision_clean})."
        ),
        ticket_type="change",
        ticket_id=change_id or None,
        portal_request_id=request_id or None,
        actor=actor,
        exclude_actor=False,
    )
