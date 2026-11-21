"""Knowledge Management APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...permissions import (
    PERM_ITSM_KNOWLEDGE_READ,
    PERM_ITSM_KNOWLEDGE_WRITE,
    has_permission,
    require_permission,
)
from ...services import audit as audit_service
from ...tenant_context import TenantContext
from ..models.knowledge import (
    KnowledgeArticleCreate,
    KnowledgeArticleTransition,
    KnowledgeArticleUpdate,
    KnowledgePreviewRequest,
)
from ..services import knowledge as knowledge_service
from ..services.knowledge import KnowledgeError

router = APIRouter(prefix="/knowledge/articles", tags=["itsm-knowledge"])


def _raise(exc: KnowledgeError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _actor(tenant: TenantContext) -> dict[str, Any]:
    return audit_service.actor_from_tenant(tenant)


def _can_write(tenant: TenantContext) -> bool:
    return has_permission(tenant, PERM_ITSM_KNOWLEDGE_WRITE)


@router.get("")
def list_articles(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    related_incident_id: str | None = Query(default=None),
    related_problem_id: str | None = Query(default=None),
    related_component_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    sort_by: str = Query(default="updated_at"),
    sort_dir: str = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_KNOWLEDGE_READ)),
) -> dict[str, Any]:
    try:
        return knowledge_service.list_articles(
            tenant_id=tenant.tenant_id,
            q=q,
            status=status,
            category=category,
            tag=tag,
            related_incident_id=related_incident_id,
            related_problem_id=related_problem_id,
            related_component_id=related_component_id,
            allow_unpublished=_can_write(tenant),
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except KnowledgeError as exc:
        _raise(exc)
        raise  # pragma: no cover


@router.post("/preview")
def preview_article_body(
    payload: KnowledgePreviewRequest,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_KNOWLEDGE_READ)),
) -> dict[str, Any]:
    """Return sanitized HTML for markdown/plain body (editor preview)."""
    try:
        result = knowledge_service.preview_body(
            body=payload.body, body_format=payload.body_format
        )
    except KnowledgeError as exc:
        _raise(exc)
        raise  # pragma: no cover
    result["tenant_id"] = tenant.tenant_id
    return result


@router.get("/suggest")
def suggest_articles(
    category: str | None = Query(default=None),
    tags: str | None = Query(
        default=None, description="Comma-separated tags to match"
    ),
    exclude_article_id: str | None = Query(default=None),
    limit: int = Query(default=5, ge=1, le=25),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_KNOWLEDGE_READ)),
) -> dict[str, Any]:
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    return knowledge_service.suggest_articles(
        tenant_id=tenant.tenant_id,
        category=category,
        tags=tag_list,
        exclude_article_id=exclude_article_id,
        limit=limit,
    )


@router.post("", status_code=201)
def create_article(
    payload: KnowledgeArticleCreate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_KNOWLEDGE_WRITE)),
) -> dict[str, Any]:
    try:
        doc = knowledge_service.create_article(
            payload, tenant_id=tenant.tenant_id, actor=_actor(tenant)
        )
    except KnowledgeError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.knowledge.create",
        resource_type="itsm_knowledge_article",
        resource_id=doc.get("article_id"),
        details={"number": doc.get("number"), "status": doc.get("status")},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/{article_id}")
def get_article(
    article_id: str,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_KNOWLEDGE_READ)),
) -> dict[str, Any]:
    doc = knowledge_service.get_article(
        article_id,
        tenant_id=tenant.tenant_id,
        allow_unpublished=_can_write(tenant),
    )
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Article '{article_id}' not found"
        )
    return doc


@router.patch("/{article_id}")
def update_article(
    article_id: str,
    payload: KnowledgeArticleUpdate,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_KNOWLEDGE_WRITE)),
) -> dict[str, Any]:
    try:
        doc = knowledge_service.update_article(
            article_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except KnowledgeError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.knowledge.update",
        resource_type="itsm_knowledge_article",
        resource_id=article_id,
        details=payload.model_dump(exclude_unset=True),
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.post("/{article_id}/transition")
def transition_article(
    article_id: str,
    payload: KnowledgeArticleTransition,
    request: Request,
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_KNOWLEDGE_WRITE)),
) -> dict[str, Any]:
    try:
        doc = knowledge_service.transition_article(
            article_id,
            payload,
            tenant_id=tenant.tenant_id,
            actor=_actor(tenant),
        )
    except KnowledgeError as exc:
        _raise(exc)
        raise  # pragma: no cover
    audit_service.record_from_tenant(
        tenant,
        action="itsm.knowledge.transition",
        resource_type="itsm_knowledge_article",
        resource_id=article_id,
        details={"status": payload.status},
        request_method=request.method,
        request_path=str(request.url.path),
    )
    return doc


@router.get("/{article_id}/activities")
def list_article_activities(
    article_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission(PERM_ITSM_KNOWLEDGE_READ)),
) -> dict[str, Any]:
    try:
        return knowledge_service.list_article_activities(
            article_id,
            tenant_id=tenant.tenant_id,
            page=page,
            page_size=page_size,
            allow_unpublished=_can_write(tenant),
        )
    except KnowledgeError as exc:
        _raise(exc)
        raise  # pragma: no cover
