"""Live HTTP ingest — logs (L3) + agent metrics/logs/file-events (L5).

Mounted without the parent ``require_user`` dependency so external collectors
and agents can authenticate with ingest keys / agent bearer tokens.
Session/Basic users remain supported for gate-smoke and lab paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from ...auth import AuthUser, require_user
from ...config import Settings, get_settings
from ...permissions import (
    PERM_MONITOR_LOGS_WRITE,
    PERM_MONITOR_TARGETS_WRITE,
    assert_permission,
)
from ...services.entitlements import EntitlementError
from ...tenant_context import TenantContext, require_tenant
from ..models.ingest import (
    FileEventIngestBatch,
    LogIngestBatch,
    MetricIngestBatch,
)
from ..services import agent_ingest as agent_ingest_service
from ..services import agents as agents_service
from ..services import ingest as ingest_service
from ..services import live_gates as live_gates_service
from ..services.agent_ingest import AgentIngestError
from ..services.agents import MonitorAgentsError
from ..services.ingest import MonitorIngestError

router = APIRouter(tags=["monitor-ingest"])
_basic = HTTPBasic(auto_error=False)


@dataclass(frozen=True)
class IngestPrincipal:
    tenant_id: str
    auth_mode: Literal["session", "ingest_key", "agent"]
    key_id: str | None = None
    stream_id: str | None = None
    agent: dict[str, Any] | None = None
    tenant: TenantContext | None = None


def _extract_bearer(authorization: str | None) -> str | None:
    auth = (authorization or "").strip()
    if not auth:
        return None
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    return None


def _extract_ingest_token(
    *,
    authorization: str | None,
    x_monitor_ingest_key: str | None,
) -> str | None:
    header_key = (x_monitor_ingest_key or "").strip()
    if header_key:
        return header_key
    return _extract_bearer(authorization)


def _raise(exc: Exception) -> None:
    if isinstance(exc, (MonitorIngestError, AgentIngestError, MonitorAgentsError, EntitlementError)):
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    raise exc


def require_log_ingest_principal(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_monitor_ingest_key: Annotated[
        str | None, Header(alias="X-Monitor-Ingest-Key")
    ] = None,
    x_monitor_agent_token: Annotated[
        str | None, Header(alias="X-Monitor-Agent-Token")
    ] = None,
) -> IngestPrincipal:
    """Authenticate via agent token, ingest key, else session/Basic + logs:write."""
    agent_token = (x_monitor_agent_token or "").strip() or None
    bearer = _extract_bearer(authorization)
    # Prefer agent token when mat_… or dedicated agent header is present.
    candidate = agent_token or (
        bearer if bearer and bearer.startswith(agents_service.TOKEN_PREFIX) else None
    )
    if candidate:
        try:
            auth = agents_service.resolve_agent_auth(
                token=candidate,
                headers=request.headers,
                settings=settings,
            )
        except MonitorAgentsError as exc:
            _raise(exc)
            raise  # pragma: no cover
        agent = auth["agent"]
        return IngestPrincipal(
            tenant_id=str(agent["tenant_id"]),
            auth_mode="agent",
            agent=agent,
        )

    token = _extract_ingest_token(
        authorization=authorization,
        x_monitor_ingest_key=x_monitor_ingest_key,
    )
    use_key = bool(token) and not (
        (authorization or "").strip().lower().startswith("basic ")
        and not (x_monitor_ingest_key or "").strip()
    )
    if use_key and token and (
        token.startswith(ingest_service.TOKEN_PREFIX)
        or (x_monitor_ingest_key or "").strip()
    ):
        try:
            key_doc = ingest_service.resolve_ingest_key(token, settings=settings)
        except MonitorIngestError as exc:
            _raise(exc)
            raise  # pragma: no cover
        return IngestPrincipal(
            tenant_id=str(key_doc["tenant_id"]),
            auth_mode="ingest_key",
            key_id=str(key_doc.get("key_id") or "") or None,
            stream_id=(str(key_doc["stream_id"]) if key_doc.get("stream_id") else None),
        )

    user: AuthUser = require_user(request, credentials, settings)
    tenant: TenantContext = require_tenant(request, user, settings)
    assert_permission(tenant, PERM_MONITOR_LOGS_WRITE)
    return IngestPrincipal(
        tenant_id=tenant.tenant_id,
        auth_mode="session",
        tenant=tenant,
    )


def require_agent_ingest_principal(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_monitor_agent_token: Annotated[
        str | None, Header(alias="X-Monitor-Agent-Token")
    ] = None,
) -> IngestPrincipal:
    """Agent token/mTLS preferred; session targets:write kept for L0 gate smoke."""
    agent_token = (x_monitor_agent_token or "").strip() or _extract_bearer(authorization)
    if agent_token or (
        settings.monitor_agent_mtls_enabled
        and request.headers.get("x-ssl-client-verify")
    ):
        try:
            auth = agents_service.resolve_agent_auth(
                token=agent_token,
                headers=request.headers,
                settings=settings,
            )
        except MonitorAgentsError as exc:
            _raise(exc)
            raise  # pragma: no cover
        agent = auth["agent"]
        return IngestPrincipal(
            tenant_id=str(agent["tenant_id"]),
            auth_mode="agent",
            agent=agent,
        )

    # Session gate-smoke / lab path (empty batches in L0).
    user: AuthUser = require_user(request, credentials, settings)
    tenant: TenantContext = require_tenant(request, user, settings)
    assert_permission(tenant, PERM_MONITOR_TARGETS_WRITE)
    return IngestPrincipal(
        tenant_id=tenant.tenant_id,
        auth_mode="session",
        tenant=tenant,
    )


async def _read_limited_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > agent_ingest_service.DEFAULT_MAX_BODY_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"body exceeds max "
                        f"{agent_ingest_service.DEFAULT_MAX_BODY_BYTES} bytes"
                    ),
                )
        except ValueError:
            pass
    raw_body = await request.body()
    if len(raw_body) > agent_ingest_service.DEFAULT_MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"body exceeds max {agent_ingest_service.DEFAULT_MAX_BODY_BYTES} bytes"
            ),
        )
    return raw_body


@router.post("/ingest/logs")
async def ingest_logs(
    request: Request,
    principal: IngestPrincipal = Depends(require_log_ingest_principal),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Accept a batch of LIVE log events (fail-closed when gates off)."""
    raw_body = await _read_limited_body(request)

    payload: LogIngestBatch
    if not raw_body or not raw_body.strip():
        payload = LogIngestBatch()
    else:
        try:
            payload = LogIngestBatch.model_validate_json(raw_body)
        except Exception as exc:  # noqa: BLE001 — pydantic / json errors
            raise HTTPException(
                status_code=422, detail=f"invalid ingest body: {exc}"
            ) from exc

    if principal.auth_mode == "agent":
        live_gates_service.require_live_capability(
            tenant_id=principal.tenant_id,
            capability="agent_ingest",
            settings=settings,
        )
        events = [item.model_dump(mode="python") for item in payload.events]
        try:
            return agent_ingest_service.ingest_agent_logs(
                tenant_id=principal.tenant_id,
                agent=principal.agent or {},
                events=events,
                default_stream_id=payload.stream_id or principal.stream_id,
                os_family=payload.os_family,
                seq=payload.seq,
                settings=settings,
            )
        except (AgentIngestError, EntitlementError) as exc:
            _raise(exc)
            raise  # pragma: no cover

    live_gates_service.require_live_capability(
        tenant_id=principal.tenant_id,
        capability="log_ingest_http",
        settings=settings,
    )
    default_stream = payload.stream_id or principal.stream_id
    events = [item.model_dump(mode="python") for item in payload.events]
    try:
        return ingest_service.ingest_log_events(
            tenant_id=principal.tenant_id,
            events=events,
            default_stream_id=default_stream,
            data_source="HTTP_INGEST",
            source_tag="agentless",
            settings=settings,
            capability="log_ingest_http",
        )
    except MonitorIngestError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/ingest/metrics")
async def ingest_metrics(
    request: Request,
    principal: IngestPrincipal = Depends(require_agent_ingest_principal),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Agent metrics ingest → LIVE metric_samples (fail-closed)."""
    live_gates_service.require_live_capability(
        tenant_id=principal.tenant_id,
        capability="agent_ingest",
        settings=settings,
    )
    raw_body = await _read_limited_body(request)
    if not raw_body or not raw_body.strip():
        payload = MetricIngestBatch()
    else:
        try:
            payload = MetricIngestBatch.model_validate_json(raw_body)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=422, detail=f"invalid ingest body: {exc}"
            ) from exc

    if principal.auth_mode != "agent":
        # Session gate-smoke: empty success marker (L0). Non-empty needs agent.
        if payload.samples:
            raise HTTPException(
                status_code=401,
                detail="agent token required for metrics ingest",
            )
        return {
            "ok": True,
            "execution_mode": "LIVE",
            "data_source": "AGENT",
            "accepted": 0,
            "rejected": 0,
            "tenant_id": principal.tenant_id,
            "live_probes": True,
            "auth_mode": "session",
        }

    samples = [item.model_dump(mode="python") for item in payload.samples]
    try:
        return agent_ingest_service.ingest_metrics(
            tenant_id=principal.tenant_id,
            agent=principal.agent or {},
            samples=samples,
            os_family=payload.os_family,
            seq=payload.seq,
            settings=settings,
        )
    except (AgentIngestError, EntitlementError) as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/ingest/file-events")
async def ingest_file_events(
    request: Request,
    principal: IngestPrincipal = Depends(require_agent_ingest_principal),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Agent file-event ingest → LIVE file_version_events (fail-closed)."""
    live_gates_service.require_live_capability(
        tenant_id=principal.tenant_id,
        capability="agent_ingest",
        settings=settings,
    )
    raw_body = await _read_limited_body(request)
    if not raw_body or not raw_body.strip():
        payload = FileEventIngestBatch()
    else:
        try:
            payload = FileEventIngestBatch.model_validate_json(raw_body)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=422, detail=f"invalid ingest body: {exc}"
            ) from exc

    if principal.auth_mode != "agent":
        if payload.events:
            raise HTTPException(
                status_code=401,
                detail="agent token required for file-event ingest",
            )
        return {
            "ok": True,
            "execution_mode": "LIVE",
            "data_source": "AGENT_FILE_WATCH",
            "accepted": 0,
            "rejected": 0,
            "tenant_id": principal.tenant_id,
            "live_probes": True,
            "auth_mode": "session",
        }

    events = [item.model_dump(mode="python") for item in payload.events]
    try:
        return agent_ingest_service.ingest_file_events(
            tenant_id=principal.tenant_id,
            agent=principal.agent or {},
            events=events,
            os_family=payload.os_family,
            seq=payload.seq,
            settings=settings,
        )
    except (AgentIngestError, EntitlementError) as exc:
        _raise(exc)
        raise  # pragma: no cover
