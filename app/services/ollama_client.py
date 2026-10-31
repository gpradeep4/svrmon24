"""Local Ollama HTTP client for SVRMON24 AI analysis.

Inspired by backend ``shared/llm.py`` patterns (httpx + JSON extraction), but
kept self-contained inside this repo. Uses Ollama's native ``/api/chat`` API
so we do not require the ``ollama`` Python package.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

import httpx

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Raised when Ollama is unavailable or returns unusable output."""

    def __init__(self, message: str, *, kind: str = "service_error") -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind  # unavailable | timeout | malformed | service_error


def extract_json_from_text(text: str) -> dict[str, Any]:
    """Parse JSON from model output, tolerating leading/trailing prose."""
    cleaned = _strip_code_fence(text)
    if not cleaned:
        raise OllamaError("Ollama returned empty content", kind="malformed")
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:
                raise OllamaError(
                    f"Ollama response is not valid JSON: {cleaned[:240]}",
                    kind="malformed",
                ) from exc
        else:
            raise OllamaError(
                f"Ollama response is not valid JSON: {cleaned[:240]}",
                kind="malformed",
            )
    if not isinstance(parsed, dict):
        raise OllamaError("Ollama JSON response must be an object", kind="malformed")
    return parsed


def _strip_code_fence(text: str) -> str:
    match = re.search(
        r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL
    )
    if match:
        return match.group(1).strip()
    return text.strip()


class OllamaClient:
    """Minimal Ollama chat client with timeouts and clear error kinds."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> OllamaClient:
        cfg = settings or get_settings()
        return cls(
            base_url=cfg.ollama_url,
            model=cfg.ollama_model,
            timeout_seconds=float(cfg.ollama_timeout_seconds),
        )

    def chat_url(self) -> str:
        return urljoin(f"{self.base_url}/", "api/chat")

    def tags_url(self) -> str:
        return urljoin(f"{self.base_url}/", "api/tags")

    def is_available(self) -> dict[str, Any]:
        """Probe Ollama; never raises — returns structured status."""
        try:
            with httpx.Client(timeout=min(5.0, self.timeout_seconds)) as client:
                response = client.get(self.tags_url())
                response.raise_for_status()
                data = response.json()
            models = [
                m.get("name")
                for m in (data.get("models") or [])
                if isinstance(m, dict)
            ]
            return {
                "ok": True,
                "base_url": self.base_url,
                "configured_model": self.model,
                "models": models,
                "model_present": any(
                    (self.model == name)
                    or (isinstance(name, str) and name.startswith(f"{self.model}:"))
                    or (isinstance(name, str) and name.split(":")[0] == self.model.split(":")[0])
                    for name in models
                ),
            }
        except httpx.TimeoutException as exc:
            return {"ok": False, "error": "timeout", "detail": str(exc)}
        except httpx.HTTPError as exc:
            return {"ok": False, "error": "unavailable", "detail": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "service_error", "detail": str(exc)}

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        selected = model or self.model
        payload = {
            "model": selected,
            "messages": messages,
            "stream": False,
            "format": "json",
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(self.chat_url(), json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise OllamaError(
                f"Ollama request timed out after {self.timeout_seconds}s",
                kind="timeout",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaError(
                f"Ollama HTTP {exc.response.status_code}: {exc.response.text[:400]}",
                kind="service_error",
            ) from exc
        except httpx.RequestError as exc:
            raise OllamaError(
                f"Ollama unavailable at {self.base_url}: {exc}",
                kind="unavailable",
            ) from exc

        message = data.get("message") or {}
        content = str(message.get("content") or "").strip()
        if not content:
            raise OllamaError("Ollama returned empty message content", kind="malformed")
        return extract_json_from_text(content)
