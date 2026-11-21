"""AI suggestion providers — local Ollama + optional OpenAI-compatible cloud.

Cloud is assist/suggestion only. API keys are resolved from environment variable
*names* (env refs) — never stored in Mongo. Provider failures raise
``SuggestionProviderError`` with a stable ``kind`` so the facade can fall back.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urljoin

import httpx

from ..config import Settings, get_settings
from .ollama_client import OllamaClient, OllamaError, extract_json_from_text

logger = logging.getLogger(__name__)

_ENV_REF_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

SOURCE_OLLAMA = "ollama"
SOURCE_CLOUD = "cloud_suggestion"
SOURCE_RULE = "rule_based_fallback"
GENERATIVE_SOURCES = frozenset({SOURCE_OLLAMA, SOURCE_CLOUD})


class SuggestionProviderError(Exception):
    """Raised when a suggestion provider is unavailable or returns bad output."""

    def __init__(self, message: str, *, kind: str = "service_error") -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind  # unavailable | timeout | malformed | service_error | disabled | misconfigured


def normalize_env_ref(value: str | None) -> str | None:
    if not value:
        return None
    ref = value.strip()
    if not ref:
        return None
    if not _ENV_REF_RE.match(ref):
        raise SuggestionProviderError(
            f"API key env ref must match {_ENV_REF_RE.pattern}",
            kind="misconfigured",
        )
    return ref


def resolve_env_secret(env_ref: str | None) -> str:
    """Read secret from an environment variable name. Never logs the value."""
    if not env_ref:
        return ""
    return os.getenv(env_ref, "").strip()


def cloud_api_key_configured(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    try:
        ref = normalize_env_ref(cfg.ai_cloud_api_key_env_ref)
    except SuggestionProviderError:
        return False
    return bool(resolve_env_secret(ref))


class OllamaSuggestionProvider:
    """Thin wrapper around ``OllamaClient`` for the shared AI facade."""

    source = SOURCE_OLLAMA

    def __init__(self, client: OllamaClient | None = None) -> None:
        self._client = client or OllamaClient.from_settings()

    @property
    def model(self) -> str:
        return self._client.model

    def chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        try:
            return self._client.chat_json(messages)
        except OllamaError as exc:
            raise SuggestionProviderError(exc.message, kind=exc.kind) from exc


class CloudSuggestionProvider:
    """OpenAI-compatible chat completions provider (JSON object responses).

    Assist / suggestion only — callers must never auto-apply writes.
    """

    source = SOURCE_CLOUD

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> CloudSuggestionProvider:
        cfg = settings or get_settings()
        if not cfg.ai_cloud_suggestions_enabled:
            raise SuggestionProviderError(
                "Cloud suggestions disabled (AI_CLOUD_SUGGESTIONS_ENABLED=false)",
                kind="disabled",
            )
        ref = normalize_env_ref(cfg.ai_cloud_api_key_env_ref)
        if not ref:
            raise SuggestionProviderError(
                "AI_CLOUD_API_KEY_ENV_REF is empty",
                kind="misconfigured",
            )
        api_key = resolve_env_secret(ref)
        if not api_key:
            raise SuggestionProviderError(
                f"Cloud API key env '{ref}' is unset or empty",
                kind="misconfigured",
            )
        return cls(
            base_url=cfg.ai_cloud_base_url,
            model=cfg.ai_cloud_model,
            api_key=api_key,
            timeout_seconds=float(cfg.ai_cloud_timeout_seconds),
        )

    def chat_url(self) -> str:
        return urljoin(f"{self.base_url}/", "chat/completions")

    def chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(self.chat_url(), json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise SuggestionProviderError(
                f"Cloud suggestion request timed out after {self.timeout_seconds}s",
                kind="timeout",
            ) from exc
        except httpx.HTTPStatusError as exc:
            # Do not echo response body (may contain provider diagnostics).
            raise SuggestionProviderError(
                f"Cloud suggestion HTTP {exc.response.status_code}",
                kind="service_error",
            ) from exc
        except httpx.RequestError as exc:
            raise SuggestionProviderError(
                f"Cloud suggestion unavailable at {self.base_url}: {exc}",
                kind="unavailable",
            ) from exc

        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise SuggestionProviderError(
                "Cloud suggestion response missing choices",
                kind="malformed",
            )
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = ""
        if isinstance(message, dict):
            content = str(message.get("content") or "").strip()
        if not content:
            raise SuggestionProviderError(
                "Cloud suggestion returned empty content",
                kind="malformed",
            )
        try:
            return extract_json_from_text(content)
        except OllamaError as exc:
            raise SuggestionProviderError(exc.message, kind="malformed") from exc
