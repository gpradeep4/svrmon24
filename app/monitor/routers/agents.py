"""Monitor agents — enroll / register / list / heartbeat / rotate / revoke (L4).

Admin + list routes live under the secured monitor router. Register and
heartbeat accept agent enrollment codes / bearer tokens (or feature-flagged
mTLS) and are mounted without the parent ``require_user`` dependency.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from ...auth import AuthUser, require_user
from ...config import Settings, get_settings
from ...permissions import (
    PERM_MONITOR_ADMIN,
    PERM_MONITOR_TARGETS_READ,
    assert_permission,
    require_permission,
)
from ...services import audit as audit_service
from ...services.entitlements import EntitlementError
from ...tenant_context import TenantContext, require_tenant
from ..models.agents import (
    AgentDesiredStatePatch,
    AgentEnrollmentCreate,
    AgentHeartbeatRequest,
    AgentRegisterRequest,
)
from ..services import agent_ingest as agent_ingest_service
from ..services import agents as agents_service
from ..services import live_gates as live_gates_service
from ..services.agent_ingest import AgentIngestError
from ..services.agents import MonitorAgentsError

# Secured (session) routes — included under /api/monitor with require_user.
router = APIRouter(prefix="/agents", tags=["monitor-agents"])

# Unsecured dual-auth routes (enrollment code / agent token / mTLS sketch).
public_router = APIRouter(prefix="/agents", tags=["monitor-agents-public"])

_basic = HTTPBasic(auto_error=False)


def _raise(exc: MonitorAgentsError | AgentIngestError | EntitlementError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _extract_bearer(authorization: str | None) -> str | None:
    auth = (authorization or "").strip()
    if not auth:
        return None
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    return None


@router.post("/enrollments", status_code=201)
def create_enrollment(
    body: AgentEnrollmentCreate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        created = agents_service.create_enrollment(
            tenant_id=tenant.tenant_id,
            created_by=tenant.user_id
            or (tenant.auth_user.email if tenant.auth_user else None)
            or (tenant.auth_user.username if tenant.auth_user else None),
            label=body.label,
            ttl_seconds=body.ttl_seconds,
            settings=settings,
        )
    except (MonitorAgentsError, EntitlementError) as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.agents.enrollment.create",
        resource_type="monitor_agent_enrollments",
        resource_id=created.get("enrollment_id"),
        details={
            "label": created.get("label"),
            "expires_at": str(created.get("expires_at")),
            # Never audit the plaintext enrollment code.
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return created


@router.get("/enrollments")
def list_enrollments(
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
) -> dict[str, Any]:
    return agents_service.list_enrollments(tenant_id=tenant.tenant_id)


@router.get("")
def list_agents(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_READ)),
) -> dict[str, Any]:
    return agents_service.list_agents(
        tenant_id=tenant.tenant_id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/{agent_id}")
def get_agent(
    agent_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_TARGETS_READ)),
) -> dict[str, Any]:
    try:
        return agents_service.get_agent(
            tenant_id=tenant.tenant_id, agent_id=agent_id
        )
    except MonitorAgentsError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/{agent_id}/revoke")
def revoke_agent(
    agent_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
) -> dict[str, Any]:
    try:
        revoked = agents_service.revoke_agent(
            tenant_id=tenant.tenant_id, agent_id=agent_id
        )
    except MonitorAgentsError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.agents.revoke",
        resource_type="monitor_agents",
        resource_id=agent_id,
        details={"status": revoked.get("status")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return revoked


@router.patch("/{agent_id}/desired-state")
def patch_desired_state(
    agent_id: str,
    body: AgentDesiredStatePatch,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_MONITOR_ADMIN)),
) -> dict[str, Any]:
    try:
        updated = agent_ingest_service.set_desired_state(
            tenant_id=tenant.tenant_id,
            agent_id=agent_id,
            watch_ids=body.watch_ids,
            stream_ids=body.stream_ids,
            target_ids=body.target_ids,
        )
    except (AgentIngestError, MonitorAgentsError) as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.agents.desired_state.update",
        resource_type="monitor_agents",
        resource_id=agent_id,
        details={
            "watch_ids": updated.get("watch_ids"),
            "stream_ids": updated.get("stream_ids"),
            "target_ids": updated.get("target_ids"),
        },
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return updated


@public_router.post("/register", status_code=201)
def register_agent(
    body: AgentRegisterRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Exchange enrollment code → agent_id + token (once). Fail-closed."""
    try:
        # Peek tenant from enrollment for gate check inside service.
        created = agents_service.register_agent(
            enrollment_code=body.enrollment_code,
            name=body.name,
            hostname=body.hostname,
            os_family=body.os_family,
            os_name=body.os_name,
            version=body.version,
            labels=body.labels,
            mtls_fingerprint=body.mtls_fingerprint,
            settings=settings,
        )
    except (MonitorAgentsError, EntitlementError) as exc:
        _raise(exc)
        raise  # pragma: no cover

    # Best-effort audit without a session user (system actor).
    try:
        from ...services import audit as audit_mod

        audit_mod.record_event(
            tenant_id=str(created.get("tenant_id") or ""),
            action="monitor.agents.register",
            resource_type="monitor_agents",
            resource_id=created.get("agent_id"),
            actor={
                "username": "monitor-agent-register",
                "user_id": None,
                "auth_method": "enrollment_code",
            },
            details={
                "name": created.get("name"),
                "os_family": created.get("os_family"),
                "enrollment_id": created.get("enrollment_id"),
            },
            request_method=request.method,
            request_path=str(request.url.path),
        )
    except Exception:  # noqa: BLE001 — audit must not block register
        pass
    return created


@public_router.post("/{agent_id}/heartbeat")
def heartbeat_agent(
    agent_id: str,
    request: Request,
    body: AgentHeartbeatRequest | None = None,
    settings: Settings = Depends(get_settings),
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_monitor_agent_token: Annotated[
        str | None, Header(alias="X-Monitor-Agent-Token")
    ] = None,
) -> dict[str, Any]:
    token = (x_monitor_agent_token or "").strip() or _extract_bearer(authorization)
    try:
        auth = agents_service.resolve_agent_auth(
            token=token,
            headers=request.headers,
            expected_agent_id=agent_id,
            settings=settings,
        )
        agent = auth["agent"]
        live_gates_service.require_live_capability(
            tenant_id=str(agent["tenant_id"]),
            capability="agent_register",
            settings=settings,
        )
        payload = body or AgentHeartbeatRequest()
        return agents_service.heartbeat_agent(
            agent_id=agent_id,
            tenant_id=str(agent["tenant_id"]),
            version=payload.version,
            hostname=payload.hostname,
            labels=payload.labels,
            status_note=payload.status_note,
            settings=settings,
        )
    except MonitorAgentsError as exc:
        _raise(exc)
        raise  # pragma: no cover


@public_router.get("/{agent_id}/desired-state")
def get_desired_state(
    agent_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_monitor_agent_token: Annotated[
        str | None, Header(alias="X-Monitor-Agent-Token")
    ] = None,
) -> dict[str, Any]:
    """Desired-state for agent token/mTLS, or session user with targets:read."""
    token = (x_monitor_agent_token or "").strip() or _extract_bearer(authorization)
    # Agent token / mTLS path (Bearer mat_… must not fall through to Basic).
    if (
        (token and token.startswith(agents_service.TOKEN_PREFIX))
        or (x_monitor_agent_token or "").strip()
        or (
            settings.monitor_agent_mtls_enabled
            and request.headers.get("x-ssl-client-verify")
        )
    ):
        try:
            auth = agents_service.resolve_agent_auth(
                token=token,
                headers=request.headers,
                expected_agent_id=agent_id,
                settings=settings,
            )
            agent = auth["agent"]
            live_gates_service.require_live_capability(
                tenant_id=str(agent["tenant_id"]),
                capability="agent_ingest",
                settings=settings,
            )
            return agent_ingest_service.get_desired_state(
                tenant_id=str(agent["tenant_id"]), agent_id=agent_id
            )
        except (MonitorAgentsError, AgentIngestError) as exc:
            _raise(exc)
            raise  # pragma: no cover

    user: AuthUser = require_user(request, credentials, settings)
    tenant: TenantContext = require_tenant(request, user, settings)
    assert_permission(tenant, PERM_MONITOR_TARGETS_READ)
    try:
        return agent_ingest_service.get_desired_state(
            tenant_id=tenant.tenant_id, agent_id=agent_id
        )
    except (AgentIngestError, MonitorAgentsError) as exc:
        _raise(exc)
        raise  # pragma: no cover


@public_router.post("/{agent_id}/rotate-token")
def rotate_token_agent(
    agent_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_monitor_agent_token: Annotated[
        str | None, Header(alias="X-Monitor-Agent-Token")
    ] = None,
) -> dict[str, Any]:
    """Agent self-rotate via token/mTLS, or session admin via Basic/session."""
    token = (x_monitor_agent_token or "").strip() or _extract_bearer(authorization)

    # Agent token / mTLS path.
    if token or (
        settings.monitor_agent_mtls_enabled
        and request.headers.get("x-ssl-client-verify")
    ):
        try:
            auth = agents_service.resolve_agent_auth(
                token=token,
                headers=request.headers,
                expected_agent_id=agent_id,
                settings=settings,
            )
            agent = auth["agent"]
            rotated = agents_service.rotate_agent_token(
                tenant_id=str(agent["tenant_id"]),
                agent_id=agent_id,
                settings=settings,
            )
            return rotated
        except (MonitorAgentsError, EntitlementError) as exc:
            _raise(exc)
            raise  # pragma: no cover

    # Session / Basic admin path on the public mount (optional convenience).
    user: AuthUser = require_user(request, credentials, settings)
    tenant: TenantContext = require_tenant(request, user, settings)
    assert_permission(tenant, PERM_MONITOR_ADMIN)
    try:
        rotated = agents_service.rotate_agent_token(
            tenant_id=tenant.tenant_id,
            agent_id=agent_id,
            settings=settings,
        )
    except (MonitorAgentsError, EntitlementError) as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="monitor.agents.rotate_token",
        resource_type="monitor_agents",
        resource_id=agent_id,
        details={"auth_mode": "admin"},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return rotated
