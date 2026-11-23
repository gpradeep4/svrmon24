"""Monitoring log streams + events API (SIMULATED + live ingest admin)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...permissions import (
    PERM_MONITOR_ADMIN,
    PERM_MONITOR_LOGS_READ,
    PERM_MONITOR_LOGS_WRITE,
    require_permission,
)
from ...services import audit as audit_service
from ...services.entitlements import EntitlementError
from ...tenant_context import TenantContext
from ..models.ingest import LogIngestKeyCreate, SyslogSourcesPut
from ..models.logs import LogAiAssistRequest
from ..services import ai_log_assist as ai_log_assist_service
from ..services import ingest as ingest_service
from ..services import logs as logs_service
from ..services.ai_log_assist import MonitorLogAiError
from ..services.ingest import MonitorIngestError
from ..services.logs import MonitorLogsError

router = APIRouter(prefix="/logs", tags=["monitor-logs"])


def _raise(
    exc: MonitorLogsError | EntitlementError | MonitorIngestError | MonitorLogAiError,
) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/streams")
def list_streams(
    q: str | None = Query(default=None),
    component_id: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    collect_mode: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_LOGS_READ)),
) -> dict[str, Any]:
    try:
        return logs_service.list_streams(
            tenant_id=tenant.tenant_id,
            q=q,
            component_id=component_id,
            source_kind=source_kind,
            status=status,
            collect_mode=collect_mode,
            page=page,
            page_size=page_size,
        )
    except MonitorLogsError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/events")
def list_events(
    q: str | None = Query(
        default=None,
        description='Search text; wrap in quotes for phrase match on message',
    ),
    severity: str | None = Query(
        default=None, description="Comma-separated severities (multi-select)"
    ),
    stream_id: str | None = Query(default=None),
    component_id: str | None = Query(default=None),
    source: str | None = Query(default=None),
    collect_mode: str | None = Query(default=None),
    attr: list[str] | None = Query(
        default=None,
        description="Repeatable attrs.* exact filters as key:value or key=value",
    ),
    cursor: str | None = Query(
        default=None, description="Opaque search_after cursor from next_cursor"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_dir: str = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_LOGS_READ)),
) -> dict[str, Any]:
    try:
        return logs_service.list_events(
            tenant_id=tenant.tenant_id,
            q=q,
            severity=severity,
            stream_id=stream_id,
            component_id=component_id,
            source=source,
            collect_mode=collect_mode,
            attr=attr,
            cursor=cursor,
            page=page,
            page_size=page_size,
            sort_dir=sort_dir,
        )
    except MonitorLogsError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.get("/ai/status")
def log_ai_status(
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_LOGS_READ)),
) -> dict[str, Any]:
    """Log AI assist status (fail-closed; assist-only safety flags)."""
    return ai_log_assist_service.log_ai_status(tenant_id=tenant.tenant_id)


@router.post("/ai/parse")
def log_ai_parse(
    payload: LogAiAssistRequest,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_LOGS_READ)),
) -> dict[str, Any]:
    """Assist-only field extraction. Does not mutate events or rules."""
    try:
        result = ai_log_assist_service.parse_log_fields(
            tenant_id=tenant.tenant_id,
            event_ids=payload.event_ids,
            messages=payload.messages,
            max_events=payload.max_events,
            force_fallback=payload.force_fallback,
        )
    except MonitorLogAiError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.logs.ai.parse",
        resource_type="log_ai",
        resource_id=tenant.tenant_id,
        details={
            "source": result.get("source"),
            "sample_count": result.get("sample_count"),
            "field_count": len(result.get("fields") or []),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return result


@router.post("/ai/suggest-filters")
def log_ai_suggest_filters(
    payload: LogAiAssistRequest,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_LOGS_READ)),
) -> dict[str, Any]:
    """Assist-only filter / log_match draft. Never writes alert rules."""
    try:
        result = ai_log_assist_service.suggest_log_filters(
            tenant_id=tenant.tenant_id,
            event_ids=payload.event_ids,
            messages=payload.messages,
            current_filters=(
                payload.current_filters.model_dump(mode="python")
                if payload.current_filters
                else None
            ),
            max_events=payload.max_events,
            force_fallback=payload.force_fallback,
        )
    except MonitorLogAiError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.logs.ai.suggest_filters",
        resource_type="log_ai",
        resource_id=tenant.tenant_id,
        details={
            "source": result.get("source"),
            "sample_count": result.get("sample_count"),
            "has_log_match_draft": bool(result.get("suggested_log_match")),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return result


@router.post("/ai/predict-narrative")
def log_ai_predict_narrative(
    payload: LogAiAssistRequest,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_LOGS_READ)),
) -> dict[str, Any]:
    """Assist-only prediction narrative draft. Never creates incidents."""
    try:
        result = ai_log_assist_service.predict_log_narrative(
            tenant_id=tenant.tenant_id,
            event_ids=payload.event_ids,
            messages=payload.messages,
            current_filters=(
                payload.current_filters.model_dump(mode="python")
                if payload.current_filters
                else None
            ),
            max_events=payload.max_events,
            force_fallback=payload.force_fallback,
        )
    except MonitorLogAiError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.logs.ai.predict_narrative",
        resource_type="log_ai",
        resource_id=tenant.tenant_id,
        details={
            "source": result.get("source"),
            "sample_count": result.get("sample_count"),
            "confidence": result.get("confidence"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return result


@router.post("/simulate-tick")
def simulate_tick(
    request: Request,
    events_per_stream: int = Query(default=3, ge=1, le=20),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
) -> dict[str, Any]:
    """Admin-only SIMULATED demo writer (no live syslog ingest)."""
    try:
        result = logs_service.simulate_tick(
            tenant_id=tenant.tenant_id,
            events_per_stream=events_per_stream,
        )
    except EntitlementError as exc:
        _raise(exc)
        raise  # pragma: no cover
    except MonitorLogsError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.logs.simulate_tick",
        resource_type="log_events",
        resource_id=tenant.tenant_id,
        details={
            "events_created": result.get("events_created"),
            "events_trimmed": result.get("events_trimmed"),
            "streams_ensured": result.get("streams_ensured"),
            "ticks_today": result.get("ticks_today"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return result


@router.get("/ingest-keys")
def list_ingest_keys(
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
) -> dict[str, Any]:
    return ingest_service.list_ingest_keys(tenant_id=tenant.tenant_id)


@router.post("/ingest-keys", status_code=201)
def create_ingest_key(
    body: LogIngestKeyCreate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
) -> dict[str, Any]:
    try:
        created = ingest_service.create_ingest_key(
            tenant_id=tenant.tenant_id,
            name=body.name,
            stream_id=body.stream_id,
        )
    except MonitorIngestError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.logs.ingest_key.create",
        resource_type="log_ingest_keys",
        resource_id=created.get("key_id"),
        details={
            "name": created.get("name"),
            "stream_id": created.get("stream_id"),
            # Never audit the plaintext token.
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return created


@router.post("/ingest-keys/{key_id}/revoke")
def revoke_ingest_key(
    key_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
) -> dict[str, Any]:
    try:
        revoked = ingest_service.revoke_ingest_key(
            tenant_id=tenant.tenant_id, key_id=key_id
        )
    except MonitorIngestError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.logs.ingest_key.revoke",
        resource_type="log_ingest_keys",
        resource_id=key_id,
        details={"status": revoked.get("status")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return revoked


@router.get("/syslog-sources")
def list_syslog_sources(
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_LOGS_READ)),
) -> dict[str, Any]:
    return ingest_service.list_syslog_sources(tenant_id=tenant.tenant_id)


@router.put("/syslog-sources")
def put_syslog_sources(
    body: SyslogSourcesPut,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_LOGS_WRITE)),
) -> dict[str, Any]:
    try:
        result = ingest_service.put_syslog_sources(
            tenant_id=tenant.tenant_id,
            sources=[item.model_dump(mode="python") for item in body.sources],
        )
    except MonitorIngestError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.logs.syslog_sources.put",
        resource_type="syslog_sources",
        resource_id=tenant.tenant_id,
        details={"count": result.get("total")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return result
