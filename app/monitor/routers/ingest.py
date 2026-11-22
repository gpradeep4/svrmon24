"""Live HTTP log ingest — dual auth (session user or ingest key).

Mounted without the parent ``require_user`` dependency so external collectors
can authenticate with ``X-Monitor-Ingest-Key`` / ``Authorization: Bearer mik_…``.
Session/Basic users with ``monitor:logs:write`` remain supported (L0 smoke).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from ...auth import AuthUser, require_user
from ...config import Settings, get_settings
from ...permissions import PERM_MONITOR_LOGS_WRITE, assert_permission
from ...tenant_context import TenantContext, require_tenant
from ..models.ingest import LogIngestBatch
from ..services import ingest as ingest_service
from ..services import live_gates as live_gates_service
from ..services.ingest import MonitorIngestError

router = APIRouter(tags=["monitor-ingest"])
_basic = HTTPBasic(auto_error=False)


@dataclass(frozen=True)
class IngestPrincipal:
    tenant_id: str
    auth_mode: Literal["session", "ingest_key"]
    key_id: str | None = None
    stream_id: str | None = None
    tenant: TenantContext | None = None


def _extract_ingest_token(
    *,
    authorization: str | None,
    x_monitor_ingest_key: str | None,
) -> str | None:
    header_key = (x_monitor_ingest_key or "").strip()
    if header_key:
        return header_key
    auth = (authorization or "").strip()
    if not auth:
        return None
    lower = auth.lower()
    if lower.startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    return None


def require_log_ingest_principal(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_monitor_ingest_key: Annotated[
        str | None, Header(alias="X-Monitor-Ingest-Key")
    ] = None,
) -> IngestPrincipal:
    """Authenticate via ingest key, else session/Basic + logs:write."""
    token = _extract_ingest_token(
        authorization=authorization,
        x_monitor_ingest_key=x_monitor_ingest_key,
    )
    # Prefer ingest key when Bearer mik_… or dedicated header is present.
    # When Authorization is Basic, require_user path handles it (L0 tests).
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
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        return IngestPrincipal(
            tenant_id=str(key_doc["tenant_id"]),
            auth_mode="ingest_key",
            key_id=str(key_doc.get("key_id") or "") or None,
            stream_id=(str(key_doc["stream_id"]) if key_doc.get("stream_id") else None),
        )

    # Session / Basic user path.
    user: AuthUser = require_user(request, credentials, settings)
    tenant: TenantContext = require_tenant(request, user, settings)
    assert_permission(tenant, PERM_MONITOR_LOGS_WRITE)
    return IngestPrincipal(
        tenant_id=tenant.tenant_id,
        auth_mode="session",
        tenant=tenant,
    )


@router.post("/ingest/logs")
async def ingest_logs(
    request: Request,
    principal: IngestPrincipal = Depends(require_log_ingest_principal),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Accept a batch of LIVE log events (fail-closed when gates off)."""
    live_gates_service.require_live_capability(
        tenant_id=principal.tenant_id,
        capability="log_ingest_http",
        settings=settings,
    )

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > ingest_service.DEFAULT_MAX_BODY_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"body exceeds max "
                        f"{ingest_service.DEFAULT_MAX_BODY_BYTES} bytes"
                    ),
                )
        except ValueError:
            pass

    raw_body = await request.body()
    if len(raw_body) > ingest_service.DEFAULT_MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"body exceeds max {ingest_service.DEFAULT_MAX_BODY_BYTES} bytes"
            ),
        )

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
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
