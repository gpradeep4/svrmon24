"""Shared AI structured-task facade for CMDB + ITSM assist.

Provider order for assist tasks:
  force_fallback → rule
  else cloud (platform on + tenant opt-in + key) → Ollama (enabled + entitlement)
  → rule fallback

Generative failures never raise to ticket/CMDB mutation callers — use
``safe_run_structured_task`` or rely on ``run_structured_task`` which always
returns a result (rule fallback on provider errors).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from pymongo import ASCENDING

from ..config import Settings, get_settings
from ..db import DatabaseUnavailableError, require_database
from ..tenancy import require_tenant_id
from . import entitlements as entitlements_service
from .ai_providers import (
    GENERATIVE_SOURCES,
    SOURCE_CLOUD,
    SOURCE_OLLAMA,
    SOURCE_RULE,
    CloudSuggestionProvider,
    OllamaSuggestionProvider,
    SuggestionProviderError,
    cloud_api_key_configured,
)
from .entitlements import EntitlementError
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)

ASSIST_USAGE_COLLECTION = "ai_assist_usage"

SHARED_LOCAL_CONTENTION_NOTE = (
    "Ollama is a shared local process (one host/GPU/CPU pool). Concurrent tenant "
    "analyze/assist requests contend for the same model capacity — expect queueing, "
    "timeouts, or slower responses under load. There is no per-tenant model "
    "isolation in v1; disable Ollama or lower max_ollama_analyses if contention "
    "hurts other workloads. Optional cloud suggestions (when opted in) use a "
    "BYO API key via env/secret ref and do not share the local GPU pool."
)

SAFETY_FLAGS = {
    "auto_transitions": False,
    "auto_approvals": False,
    "auto_close_tickets": False,
    "secrets_stored_in_mongo": False,
    "assist_only_cloud": True,
}


@dataclass(frozen=True)
class StructuredTaskResult:
    """Normalized result from ``run_structured_task``."""

    payload: dict[str, Any]
    source: str
    model: str | None
    fallback_reason: str | None
    task_key: str

    def as_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "source": self.source,
            "model": self.model,
            "task_key": self.task_key,
        }
        if self.fallback_reason:
            meta["fallback_reason"] = self.fallback_reason
        return meta


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _usage_collection():
    return require_database()[ASSIST_USAGE_COLLECTION]


def ensure_assist_usage_indexes() -> None:
    """Idempotent indexes for generative assist usage accounting."""
    try:
        coll = _usage_collection()
    except DatabaseUnavailableError:
        return
    coll.create_index(
        [("tenant_id", ASCENDING), ("source", ASCENDING), ("created_at", ASCENDING)]
    )
    coll.create_index([("tenant_id", ASCENDING), ("task_key", ASCENDING)])


def record_assist_usage(
    *,
    tenant_id: str,
    task_key: str,
    source: str,
    model: str | None = None,
) -> None:
    """Persist one generative assist debit (rule fallback must not call this)."""
    if source not in GENERATIVE_SOURCES:
        return
    tid = require_tenant_id(tenant_id)
    try:
        ensure_assist_usage_indexes()
        _usage_collection().insert_one(
            {
                "tenant_id": tid,
                "task_key": task_key,
                "source": source,
                "model": model,
                "created_at": _now(),
            }
        )
    except DatabaseUnavailableError:
        logger.warning("ai_assist_usage_skip_db_unavailable tenant_id=%s", tid)
    except Exception:  # noqa: BLE001 — usage must never break assist path
        logger.exception("ai_assist_usage_record_failed tenant_id=%s", tid)


def count_assist_usage(*, tenant_id: str) -> int:
    """Count non-diagnostic generative assists for the tenant."""
    tid = require_tenant_id(tenant_id)
    try:
        return int(
            _usage_collection().count_documents(
                {"tenant_id": tid, "source": {"$in": list(GENERATIVE_SOURCES)}}
            )
        )
    except DatabaseUnavailableError:
        return 0


def tenant_cloud_suggestions_opt_in(tenant_id: str) -> bool:
    """Per-tenant opt-in flag (default false)."""
    from . import tenants as tenants_service

    tid = require_tenant_id(tenant_id)
    tenant = tenants_service.get_tenant(tid)
    if not tenant:
        return False
    return bool(tenant.get("ai_cloud_suggestions_opt_in"))


def set_tenant_cloud_suggestions_opt_in(tenant_id: str, enabled: bool) -> dict[str, Any]:
    """Set tenant cloud-suggestion opt-in (org/platform admin path)."""
    from . import tenants as tenants_service

    return tenants_service.set_ai_cloud_suggestions_opt_in(tenant_id, enabled)


def cloud_eligible(*, tenant_id: str, settings: Settings | None = None) -> dict[str, Any]:
    """Whether cloud suggestions can be attempted for this tenant."""
    cfg = settings or get_settings()
    platform_on = bool(cfg.ai_cloud_suggestions_enabled)
    opt_in = tenant_cloud_suggestions_opt_in(tenant_id) if platform_on else False
    key_ok = cloud_api_key_configured(cfg) if platform_on else False
    will_use = platform_on and opt_in and key_ok
    detail = None
    if not platform_on:
        detail = "AI_CLOUD_SUGGESTIONS_ENABLED is false (default)."
    elif not opt_in:
        detail = "Tenant has not opted in to cloud suggestions."
    elif not key_ok:
        detail = (
            f"API key env '{cfg.ai_cloud_api_key_env_ref}' is unset or empty "
            "(secret ref only — never stored in Mongo)."
        )
    return {
        "platform_enabled": platform_on,
        "tenant_opt_in": opt_in,
        "api_key_configured": key_ok,
        "will_use": will_use,
        "base_url": cfg.ai_cloud_base_url,
        "configured_model": cfg.ai_cloud_model,
        "api_key_env_ref": cfg.ai_cloud_api_key_env_ref,
        "timeout_seconds": cfg.ai_cloud_timeout_seconds,
        "detail": detail,
    }


def _try_provider_json(
    *,
    provider_name: str,
    chat_fn: Callable[[list[dict[str, str]]], dict[str, Any]],
    messages: list[dict[str, str]],
    validate_fn: Callable[[dict[str, Any]], None] | None,
    model: str,
) -> tuple[dict[str, Any], str, str]:
    raw = chat_fn(messages)
    if validate_fn is not None:
        try:
            validate_fn(raw)
        except SuggestionProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — normalize validator errors
            raise SuggestionProviderError(str(exc), kind="malformed") from exc
    return raw, provider_name, model


def run_structured_task(
    *,
    task_key: str,
    tenant_id: str,
    messages: list[dict[str, str]],
    fallback_builder: Callable[[str], dict[str, Any]],
    validate_fn: Callable[[dict[str, Any]], None] | None = None,
    force_fallback: bool = False,
    record_usage: bool = True,
    ollama_client: OllamaClient | None = None,
    settings: Settings | None = None,
) -> StructuredTaskResult:
    """Run a structured JSON assist task with cloud → Ollama → rule fallback.

    Always returns a result. Provider/entitlement failures become rule fallback
    with a ``fallback_reason`` — they do not raise (so ticket mutations stay safe).
    """
    tid = require_tenant_id(tenant_id)
    cfg = settings or get_settings()
    key = (task_key or "assist").strip() or "assist"

    def _rule(reason: str) -> StructuredTaskResult:
        payload = fallback_builder(reason)
        # Ensure callers see consistent source labeling even if builder omits it.
        if isinstance(payload, dict) and not payload.get("source"):
            payload = {**payload, "source": SOURCE_RULE, "fallback_reason": reason}
        return StructuredTaskResult(
            payload=payload,
            source=str(payload.get("source") or SOURCE_RULE),
            model=payload.get("model") if isinstance(payload, dict) else None,
            fallback_reason=reason,
            task_key=key,
        )

    if force_fallback:
        return _rule("forced_fallback_for_tests_or_operator_request")

    # Entitlement gates *generative* providers; rule fallback always available.
    entitlement_blocked = False
    entitlement_reason = ""
    try:
        entitlements_service.assert_can_run_ollama_analysis(tid)
    except EntitlementError as exc:
        entitlement_blocked = True
        entitlement_reason = f"ollama_entitlement_limit: {exc.message}"

    last_error: str | None = None

    if not entitlement_blocked:
        cloud = cloud_eligible(tenant_id=tid, settings=cfg)
        if cloud["will_use"]:
            try:
                provider = CloudSuggestionProvider.from_settings(cfg)
                raw, source, model = _try_provider_json(
                    provider_name=SOURCE_CLOUD,
                    chat_fn=provider.chat_json,
                    messages=messages,
                    validate_fn=validate_fn,
                    model=provider.model,
                )
                if record_usage:
                    record_assist_usage(
                        tenant_id=tid, task_key=key, source=source, model=model
                    )
                return StructuredTaskResult(
                    payload=raw,
                    source=source,
                    model=model,
                    fallback_reason=None,
                    task_key=key,
                )
            except SuggestionProviderError as exc:
                last_error = f"cloud_{exc.kind}: {exc.message}"
                logger.warning(
                    "ai_cloud_fallback task=%s tenant=%s kind=%s",
                    key,
                    tid,
                    exc.kind,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"cloud_service_error: {exc}"
                logger.exception("ai_cloud_unexpected task=%s tenant=%s", key, tid)

        if cfg.ollama_enabled:
            try:
                ollama = OllamaSuggestionProvider(
                    client=ollama_client or OllamaClient.from_settings(cfg)
                )
                raw, source, model = _try_provider_json(
                    provider_name=SOURCE_OLLAMA,
                    chat_fn=ollama.chat_json,
                    messages=messages,
                    validate_fn=validate_fn,
                    model=ollama.model,
                )
                if record_usage:
                    record_assist_usage(
                        tenant_id=tid, task_key=key, source=source, model=model
                    )
                return StructuredTaskResult(
                    payload=raw,
                    source=source,
                    model=model,
                    fallback_reason=None,
                    task_key=key,
                )
            except SuggestionProviderError as exc:
                last_error = f"ollama_{exc.kind}: {exc.message}"
                logger.warning(
                    "ai_ollama_fallback task=%s tenant=%s kind=%s",
                    key,
                    tid,
                    exc.kind,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"ollama_service_error: {exc}"
                logger.exception("ai_ollama_unexpected task=%s tenant=%s", key, tid)
        elif last_error is None:
            last_error = (
                "ollama_disabled: set OLLAMA_ENABLED=true to use local Ollama"
            )
    else:
        return _rule(entitlement_reason)

    # Prefer the most specific failure reason; if cloud failed and ollama off,
    # still surface ollama_disabled after cloud reason.
    if last_error and "ollama_disabled" in last_error and cloud_eligible(
        tenant_id=tid, settings=cfg
    ).get("platform_enabled"):
        # Keep cloud failure as primary when cloud was attempted.
        pass
    reason = last_error or (
        "ollama_disabled: set OLLAMA_ENABLED=true to use local Ollama"
    )
    return _rule(reason)


def safe_run_structured_task(
    *,
    task_key: str,
    tenant_id: str,
    messages: list[dict[str, str]],
    fallback_builder: Callable[[str], dict[str, Any]],
    validate_fn: Callable[[dict[str, Any]], None] | None = None,
    force_fallback: bool = False,
    record_usage: bool = True,
    ollama_client: OllamaClient | None = None,
    settings: Settings | None = None,
) -> StructuredTaskResult:
    """Like ``run_structured_task`` but also guards against fallback_builder errors.

    Use around ticket mutation side-calls so AI never fails the host write.
    """
    try:
        return run_structured_task(
            task_key=task_key,
            tenant_id=tenant_id,
            messages=messages,
            fallback_builder=fallback_builder,
            validate_fn=validate_fn,
            force_fallback=force_fallback,
            record_usage=record_usage,
            ollama_client=ollama_client,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "ai_safe_run_caught task=%s tenant=%s", task_key, tenant_id
        )
        reason = f"ai_internal_error: {exc}"
        try:
            payload = fallback_builder(reason)
        except Exception:  # noqa: BLE001
            payload = {
                "source": SOURCE_RULE,
                "fallback_reason": reason,
                "executive_summary": "AI assist unavailable; rule fallback failed.",
            }
        return StructuredTaskResult(
            payload=payload,
            source=str(payload.get("source") or SOURCE_RULE),
            model=None,
            fallback_reason=reason,
            task_key=task_key,
        )


def ai_runtime_status(*, tenant_id: str) -> dict[str, Any]:
    """Combined provider + entitlement status for CMDB/ITSM UIs."""
    settings = get_settings()
    tid = require_tenant_id(tenant_id)
    entitlement = entitlements_service.ollama_analysis_allowed(tid)
    cloud = cloud_eligible(tenant_id=tid, settings=settings)

    ollama_block: dict[str, Any] = {
        "enabled": bool(settings.ollama_enabled),
        "base_url": settings.ollama_url,
        "configured_model": settings.ollama_model,
        "timeout_seconds": settings.ollama_timeout_seconds,
    }
    will_use_ollama = False
    if not settings.ollama_enabled:
        ollama_block.update(
            {
                "ok": False,
                "error": "disabled",
                "detail": (
                    "OLLAMA_ENABLED is false (default). Set OLLAMA_ENABLED=true "
                    "to probe/use local Ollama."
                ),
                "will_use": False,
            }
        )
    elif entitlement.get("limited"):
        probe = OllamaClient.from_settings(settings).is_available()
        ollama_block.update(probe)
        ollama_block.update(
            {
                "will_use": False,
                "error": ollama_block.get("error") or "entitlement_limit",
                "detail": (
                    f"Tenant generative AI limit reached "
                    f"({entitlement.get('used')}/{entitlement.get('limit')}). "
                    "Assist will use rule-based fallback."
                ),
            }
        )
    else:
        probe = OllamaClient.from_settings(settings).is_available()
        ollama_block.update(probe)
        will_use_ollama = bool(probe.get("ok")) and not cloud["will_use"]
        # When cloud will be preferred, Ollama is standby.
        ollama_block["will_use"] = will_use_ollama
        if cloud["will_use"]:
            ollama_block["standby"] = True
            ollama_block["detail"] = (
                "Cloud suggestions preferred when eligible; Ollama used on cloud failure."
            )

    providers_enabled = {
        "ollama": bool(settings.ollama_enabled),
        "cloud_suggestions": bool(cloud["platform_enabled"]),
    }

    # Flat compatibility fields for diagnostics UI / existing tests.
    flat: dict[str, Any] = {
        "enabled": bool(settings.ollama_enabled),
        "base_url": settings.ollama_url,
        "configured_model": settings.ollama_model,
        "timeout_seconds": settings.ollama_timeout_seconds,
        "ok": bool(ollama_block.get("ok")) if settings.ollama_enabled else False,
        "will_use_ollama": bool(ollama_block.get("will_use")),
        "will_use_cloud": bool(cloud.get("will_use")),
        "external_providers": bool(cloud["platform_enabled"]),
        "external_providers_note": (
            "Optional OpenAI-compatible cloud suggestions are assist-only, "
            "disabled by default, tenant opt-in, BYO key via env ref — never Mongo."
        ),
    }
    for key in ("error", "detail", "models", "model_present"):
        if key in ollama_block:
            flat[key] = ollama_block[key]

    return {
        "entitlement": entitlement,
        "shared_local_contention": SHARED_LOCAL_CONTENTION_NOTE,
        "rule_fallback_always_available": True,
        "safety": dict(SAFETY_FLAGS),
        "providers": providers_enabled,
        "ollama": ollama_block,
        "cloud_suggestions": cloud,
        **flat,
    }
