"""Monitoring alert rules + instances API (SIMULATED evaluation)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...permissions import (
    PERM_MONITOR_ALERTS_READ,
    PERM_MONITOR_ALERTS_WRITE,
    require_permission,
)
from ...services import audit as audit_service
from ...services.entitlements import EntitlementError
from ...tenant_context import TenantContext
from ..models.alerts import AlertRuleCreate, AlertRulePatch, LinkSuggestedIncident
from ..services import alerts as alerts_service
from ..services.alerts import MonitorAlertsError

router = APIRouter(prefix="/alerts", tags=["monitor-alerts"])


def _raise(exc: MonitorAlertsError | EntitlementError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> str | None:
    user = tenant.auth_user
    return (
        getattr(user, "username", None)
        or tenant.user_id
        or getattr(user, "subject", None)
        or getattr(user, "email", None)
    )


@router.get("/rules")
def list_rules(
    q: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ALERTS_READ)),
) -> dict[str, Any]:
    try:
        return alerts_service.list_rules(
            tenant_id=tenant.tenant_id,
            q=q,
            enabled=enabled,
            page=page,
            page_size=page_size,
        )
    except MonitorAlertsError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/rules", status_code=201)
def create_rule(
    request: Request,
    body: AlertRuleCreate,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ALERTS_WRITE)),
) -> dict[str, Any]:
    try:
        doc = alerts_service.create_rule(
            tenant_id=tenant.tenant_id,
            payload=body.model_dump(),
        )
    except EntitlementError as exc:
        _raise(exc)
        raise  # pragma: no cover
    except MonitorAlertsError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.alerts.rule_create",
        resource_type="alert_rules",
        resource_id=doc.get("rule_id"),
        details={
            "name": doc.get("name"),
            "severity": doc.get("severity"),
            "condition_type": (doc.get("condition") or {}).get("type"),
            "enabled": doc.get("enabled"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/rules/{rule_id}")
def get_rule(
    rule_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ALERTS_READ)),
) -> dict[str, Any]:
    doc = alerts_service.get_rule(tenant_id=tenant.tenant_id, rule_id=rule_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    return doc


@router.patch("/rules/{rule_id}")
def patch_rule(
    rule_id: str,
    request: Request,
    body: AlertRulePatch,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ALERTS_WRITE)),
) -> dict[str, Any]:
    try:
        doc = alerts_service.patch_rule(
            tenant_id=tenant.tenant_id,
            rule_id=rule_id,
            payload=body.model_dump(exclude_unset=True),
        )
    except MonitorAlertsError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.alerts.rule_update",
        resource_type="alert_rules",
        resource_id=doc.get("rule_id"),
        details={
            "name": doc.get("name"),
            "enabled": doc.get("enabled"),
            "severity": doc.get("severity"),
            "patched_fields": sorted(body.model_dump(exclude_unset=True).keys()),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ALERTS_WRITE)),
) -> dict[str, Any]:
    try:
        result = alerts_service.delete_rule(
            tenant_id=tenant.tenant_id, rule_id=rule_id
        )
    except MonitorAlertsError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.alerts.rule_delete",
        resource_type="alert_rules",
        resource_id=rule_id,
        details={"deleted": True},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return result


@router.get("/instances")
def list_instances(
    status: str | None = Query(default=None),
    rule_id: str | None = Query(default=None),
    component_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ALERTS_READ)),
) -> dict[str, Any]:
    try:
        return alerts_service.list_instances(
            tenant_id=tenant.tenant_id,
            status=status,
            rule_id=rule_id,
            component_id=component_id,
            q=q,
            page=page,
            page_size=page_size,
        )
    except MonitorAlertsError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/instances/{alert_id}")
def get_instance(
    alert_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ALERTS_READ)),
) -> dict[str, Any]:
    doc = alerts_service.get_instance(
        tenant_id=tenant.tenant_id, alert_id=alert_id
    )
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Alert '{alert_id}' not found"
        )
    return doc


@router.post("/instances/{alert_id}/ack")
def ack_instance(
    alert_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ALERTS_WRITE)),
) -> dict[str, Any]:
    try:
        doc = alerts_service.ack_instance(
            tenant_id=tenant.tenant_id,
            alert_id=alert_id,
            actor=_actor(tenant),
        )
    except MonitorAlertsError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.alerts.ack",
        resource_type="alert_instances",
        resource_id=alert_id,
        details={"status": doc.get("status")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/instances/{alert_id}/resolve")
def resolve_instance(
    alert_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ALERTS_WRITE)),
) -> dict[str, Any]:
    try:
        doc = alerts_service.resolve_instance(
            tenant_id=tenant.tenant_id,
            alert_id=alert_id,
            actor=_actor(tenant),
        )
    except MonitorAlertsError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.alerts.resolve",
        resource_type="alert_instances",
        resource_id=alert_id,
        details={"status": doc.get("status")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/evaluate")
def evaluate_alerts(
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ALERTS_WRITE)),
) -> dict[str, Any]:
    """Evaluate enabled rules against SIMULATED metrics/logs/file events."""
    try:
        result = alerts_service.evaluate_rules(tenant_id=tenant.tenant_id)
    except MonitorAlertsError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.alerts.evaluate",
        resource_type="alert_instances",
        resource_id=tenant.tenant_id,
        details={
            "rules_evaluated": result.get("rules_evaluated"),
            "created": result.get("created"),
            "open_count": result.get("open_count"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return result


@router.post("/instances/{alert_id}/suggest-incident")
def suggest_incident(
    alert_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ALERTS_WRITE)),
) -> dict[str, Any]:
    """Return an ITSM incident **draft** from alert evidence (assist only).

    Does **not** create an incident. Apply via ``POST /api/itsm/incidents``
    with ``itsm:incident:write`` and explicit user action.
    """
    try:
        result = alerts_service.suggest_incident(
            tenant_id=tenant.tenant_id, alert_id=alert_id
        )
    except MonitorAlertsError as exc:
        _raise(exc)
        raise  # pragma: no cover
    draft = result.get("draft") or {}
    audit_service.record_from_tenant(
        tenant,
        action="monitor.alerts.suggest_incident",
        resource_type="alert_instances",
        resource_id=alert_id,
        details={
            "source": result.get("source"),
            "auto_create": False,
            "priority": draft.get("priority"),
            "severity": draft.get("severity"),
            "ci_links": len(draft.get("ci_links") or []),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return result


@router.post("/instances/{alert_id}/link-incident")
def link_suggested_incident(
    alert_id: str,
    request: Request,
    body: LinkSuggestedIncident,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ALERTS_WRITE)),
) -> dict[str, Any]:
    """Stamp ``suggested_incident_id`` after human Apply via ITSM API.

    Monitoring-only update — never writes ITSM collections.
    """
    try:
        doc = alerts_service.link_suggested_incident(
            tenant_id=tenant.tenant_id,
            alert_id=alert_id,
            incident_id=body.incident_id,
        )
    except MonitorAlertsError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.alerts.link_incident",
        resource_type="alert_instances",
        resource_id=alert_id,
        details={"suggested_incident_id": doc.get("suggested_incident_id")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc
