"""Knowledge Management service — ITSM DB only; related refs are ids only."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection

from ...db import require_itsm_database
from ...serialization import serialize_document
from ...tenancy import merge_tenant_filter, require_tenant_id, stamp_tenant_id
from ..models.knowledge import (
    KNOWLEDGE_STATUSES,
    KNOWLEDGE_TRANSITIONS,
    KnowledgeArticleCreate,
    KnowledgeArticleTransition,
    KnowledgeArticleUpdate,
)
from . import activities as activities_service
from .indexes import COUNTERS, KNOWLEDGE_ARTICLES, ensure_itsm_indexes


class KnowledgeError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[KNOWLEDGE_ARTICLES]


def _counters() -> Collection:
    ensure_itsm_indexes()
    return require_itsm_database()[COUNTERS]


def _new_article_id() -> str:
    return f"KB-{uuid.uuid4().hex[:10].upper()}"


def _next_number(*, tenant_id: str) -> int:
    tid = require_tenant_id(tenant_id)
    doc = _counters().find_one_and_update(
        {"tenant_id": tid, "counter_key": "knowledge"},
        {
            "$inc": {"value": 1},
            "$setOnInsert": {"tenant_id": tid, "counter_key": "knowledge"},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc.get("value") or 1)


def _actor_fields(actor: dict[str, Any] | None) -> dict[str, str | None]:
    actor = actor or {}
    return {
        "user_id": actor.get("user_id") or actor.get("username"),
        "username": actor.get("username") or actor.get("user_id"),
    }


def _clean_id_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _clean_tags(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        tag = str(raw or "").strip().lower()
        if not tag or tag in seen:
            continue
        if len(tag) > 64:
            tag = tag[:64]
        seen.add(tag)
        out.append(tag)
        if len(out) >= 32:
            break
    return out


def get_article(
    article_id: str,
    *,
    tenant_id: str,
    allow_unpublished: bool = False,
) -> dict[str, Any] | None:
    tid = require_tenant_id(tenant_id)
    doc = _coll().find_one({"tenant_id": tid, "article_id": article_id})
    if doc is None:
        return None
    if not allow_unpublished and doc.get("status") != "published":
        return None
    return serialize_document(doc)


def list_articles(
    *,
    tenant_id: str,
    q: str | None = None,
    status: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    related_incident_id: str | None = None,
    related_problem_id: str | None = None,
    related_component_id: str | None = None,
    allow_unpublished: bool = False,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    clauses: list[dict[str, Any]] = []

    if status:
        if status not in KNOWLEDGE_STATUSES:
            raise KnowledgeError(f"Invalid status '{status}'")
        if not allow_unpublished and status != "published":
            raise KnowledgeError(
                "Viewers may only list published articles", status_code=403
            )
        clauses.append({"status": status})
    elif not allow_unpublished:
        clauses.append({"status": "published"})

    if category and category.strip():
        clauses.append(
            {
                "category": {
                    "$regex": f"^{re.escape(category.strip())}$",
                    "$options": "i",
                }
            }
        )
    if tag and tag.strip():
        clauses.append({"tags": tag.strip().lower()})
    if related_incident_id and related_incident_id.strip():
        clauses.append({"related_incident_ids": related_incident_id.strip()})
    if related_problem_id and related_problem_id.strip():
        clauses.append({"related_problem_ids": related_problem_id.strip()})
    if related_component_id and related_component_id.strip():
        clauses.append({"related_component_ids": related_component_id.strip()})
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        clauses.append(
            {
                "$or": [
                    {"title": rx},
                    {"body": rx},
                    {"article_id": rx},
                    {"number_display": rx},
                    {"category": rx},
                    {"tags": rx},
                ]
            }
        )

    query: dict[str, Any] | None = {"$and": clauses} if clauses else None
    scoped = merge_tenant_filter(query, tid)

    allowed_sort = {
        "updated_at",
        "created_at",
        "number",
        "status",
        "title",
        "article_id",
        "category",
        "published_at",
    }
    sort_field = sort_by if sort_by in allowed_sort else "updated_at"
    direction = DESCENDING if str(sort_dir).lower() != "asc" else ASCENDING

    coll = _coll()
    total = coll.count_documents(scoped)
    cursor = (
        coll.find(scoped)
        .sort([(sort_field, direction)])
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


def suggest_articles(
    *,
    tenant_id: str,
    category: str | None = None,
    tags: list[str] | None = None,
    exclude_article_id: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Suggest published articles by category and/or overlapping tags."""
    tid = require_tenant_id(tenant_id)
    limit = min(max(1, int(limit)), 25)
    clean_tags = _clean_tags(tags)
    category_norm = (category or "").strip()

    if not category_norm and not clean_tags:
        return {"items": [], "count": 0, "tenant_id": tid, "match": "none"}

    or_clauses: list[dict[str, Any]] = []
    if category_norm:
        or_clauses.append(
            {
                "category": {
                    "$regex": f"^{re.escape(category_norm)}$",
                    "$options": "i",
                }
            }
        )
    if clean_tags:
        or_clauses.append({"tags": {"$in": clean_tags}})

    query: dict[str, Any] = {"status": "published", "$or": or_clauses}
    if exclude_article_id:
        query["article_id"] = {"$ne": exclude_article_id.strip()}
    scoped = merge_tenant_filter(query, tid)

    coll = _coll()
    candidates = list(
        coll.find(scoped).sort([("updated_at", DESCENDING)]).limit(limit * 4)
    )

    scored: list[tuple[int, dict[str, Any]]] = []
    cat_lower = category_norm.lower()
    tag_set = set(clean_tags)
    for doc in candidates:
        score = 0
        doc_cat = str(doc.get("category") or "").strip().lower()
        if cat_lower and doc_cat == cat_lower:
            score += 10
        doc_tags = {str(t).lower() for t in (doc.get("tags") or [])}
        overlap = len(tag_set & doc_tags)
        score += overlap * 3
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("updated_at") or "")))

    items = []
    for score, doc in scored[:limit]:
        row = serialize_document(doc)
        if isinstance(row, dict):
            row["match_score"] = score
            items.append(row)

    return {
        "items": items,
        "count": len(items),
        "tenant_id": tid,
        "match": "category_or_tags",
    }


def create_article(
    payload: KnowledgeArticleCreate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    if payload.status not in KNOWLEDGE_STATUSES:
        raise KnowledgeError(f"Invalid status '{payload.status}'")

    now = _now()
    number = _next_number(tenant_id=tid)
    article_id = _new_article_id()
    who = _actor_fields(actor)
    status = payload.status
    published_at = now if status == "published" else None
    retired_at = now if status == "retired" else None

    doc: dict[str, Any] = {
        "article_id": article_id,
        "number": number,
        "number_display": f"KB-{number:05d}",
        "title": payload.title.strip(),
        "body": payload.body.strip(),
        "status": status,
        "category": (payload.category or "").strip() or None,
        "tags": _clean_tags(payload.tags),
        "related_incident_ids": _clean_id_list(payload.related_incident_ids),
        "related_problem_ids": _clean_id_list(payload.related_problem_ids),
        "related_component_ids": _clean_id_list(payload.related_component_ids),
        "published_at": published_at,
        "retired_at": retired_at,
        "created_at": now,
        "updated_at": now,
        "created_by": who["username"],
        "updated_by": who["username"],
    }
    stamp_tenant_id(doc, tenant_id=tid)
    _coll().insert_one(doc)

    activities_service.append_activity(
        tenant_id=tid,
        ticket_type="knowledge",
        ticket_id=article_id,
        activity_type="created",
        message=f"Knowledge article created ({doc['number_display']})",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        to_value=status,
    )
    return serialize_document(doc)  # type: ignore[return-value]


def update_article(
    article_id: str,
    payload: KnowledgeArticleUpdate,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "article_id": article_id})
    if existing is None:
        raise KnowledgeError(f"Article '{article_id}' not found", status_code=404)

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return serialize_document(existing)  # type: ignore[return-value]

    if "title" in updates and updates["title"] is not None:
        updates["title"] = str(updates["title"]).strip()
    if "body" in updates and updates["body"] is not None:
        updates["body"] = str(updates["body"]).strip()
    if "category" in updates and updates["category"] is not None:
        updates["category"] = str(updates["category"]).strip() or None
    if "tags" in updates:
        updates["tags"] = _clean_tags(updates["tags"])
    if "related_incident_ids" in updates:
        updates["related_incident_ids"] = _clean_id_list(updates["related_incident_ids"])
    if "related_problem_ids" in updates:
        updates["related_problem_ids"] = _clean_id_list(updates["related_problem_ids"])
    if "related_component_ids" in updates:
        updates["related_component_ids"] = _clean_id_list(
            updates["related_component_ids"]
        )

    who = _actor_fields(actor)
    updates["updated_at"] = _now()
    updates["updated_by"] = who["username"]

    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "article_id": article_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise KnowledgeError(f"Article '{article_id}' not found", status_code=404)

    activities_service.append_activity(
        tenant_id=tid,
        ticket_type="knowledge",
        ticket_id=article_id,
        activity_type="system",
        message="Knowledge article updated",
        actor_user_id=who["user_id"],
        actor_username=who["username"],
    )
    return serialize_document(doc)  # type: ignore[return-value]


def transition_article(
    article_id: str,
    payload: KnowledgeArticleTransition,
    *,
    tenant_id: str,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    existing = _coll().find_one({"tenant_id": tid, "article_id": article_id})
    if existing is None:
        raise KnowledgeError(f"Article '{article_id}' not found", status_code=404)

    current = str(existing.get("status") or "")
    target = payload.status
    if target not in KNOWLEDGE_STATUSES:
        raise KnowledgeError(f"Invalid status '{target}'")
    allowed = KNOWLEDGE_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise KnowledgeError(
            f"Cannot transition knowledge article from '{current}' to '{target}'"
        )

    who = _actor_fields(actor)
    now = _now()
    updates: dict[str, Any] = {
        "status": target,
        "updated_at": now,
        "updated_by": who["username"],
    }
    if target == "published":
        updates["published_at"] = now
        updates["retired_at"] = None
    elif target == "retired":
        updates["retired_at"] = now
    elif target == "draft":
        updates["retired_at"] = None

    doc = _coll().find_one_and_update(
        {"tenant_id": tid, "article_id": article_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise KnowledgeError(f"Article '{article_id}' not found", status_code=404)

    comment = (payload.comment or "").strip()
    message = f"Status {current} → {target}"
    if comment:
        message = f"{message}: {comment}"
    activities_service.append_activity(
        tenant_id=tid,
        ticket_type="knowledge",
        ticket_id=article_id,
        activity_type="status_change",
        message=message,
        actor_user_id=who["user_id"],
        actor_username=who["username"],
        from_value=current,
        to_value=target,
    )
    return serialize_document(doc)  # type: ignore[return-value]


def list_article_activities(
    article_id: str,
    *,
    tenant_id: str,
    page: int = 1,
    page_size: int = 50,
    allow_unpublished: bool = False,
) -> dict[str, Any]:
    tid = require_tenant_id(tenant_id)
    raw = _coll().find_one({"tenant_id": tid, "article_id": article_id})
    if raw is None:
        raise KnowledgeError(f"Article '{article_id}' not found", status_code=404)
    if not allow_unpublished and raw.get("status") != "published":
        raise KnowledgeError(f"Article '{article_id}' not found", status_code=404)
    return activities_service.list_activities(
        tenant_id=tid,
        ticket_type="knowledge",
        ticket_id=article_id,
        page=page,
        page_size=page_size,
    )
