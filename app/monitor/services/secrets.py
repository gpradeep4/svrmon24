"""Resolve monitor check ``secret_ref`` values (env refs; lab plaintext flagged).

Never log secret values. Prefer ``env:VAR_NAME``; plaintext lab values must use
``insecure:`` / ``plaintext:`` prefixes and set ``secret_insecure_demo``.
"""

from __future__ import annotations

import os
import re
from typing import Any

_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class SecretRefError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def normalize_secret_ref(raw: Any) -> tuple[str | None, bool]:
    """Return ``(stored_ref, secret_insecure_demo)``.

    Accepted forms:
    - ``None`` / empty → ``(None, False)``
    - ``env:VAR_NAME`` or bare ``VAR_NAME`` matching env name → env ref (secure)
    - ``insecure:value`` / ``plaintext:value`` → lab plaintext (flagged)
    """
    if raw is None:
        return None, False
    text = str(raw).strip()
    if not text:
        return None, False

    lower = text.lower()
    if lower.startswith("insecure:") or lower.startswith("plaintext:"):
        # Keep original prefix+value so runtime can extract the secret.
        return text, True

    if lower.startswith("env:"):
        name = text[4:].strip()
        if not _ENV_NAME_RE.match(name):
            raise SecretRefError(
                f"secret_ref env name must match {_ENV_NAME_RE.pattern}"
            )
        return f"env:{name}", False

    # Bare env-style name → treat as env ref (no plaintext in Mongo).
    if _ENV_NAME_RE.match(text):
        return f"env:{text}", False

    raise SecretRefError(
        "secret_ref must be env:VAR_NAME (or bare VAR_NAME), "
        "or insecure:/plaintext: for lab demos"
    )


def resolve_secret_ref(secret_ref: str | None) -> dict[str, Any]:
    """Resolve a stored secret_ref to a runtime value.

    Returns dict with keys: ``value``, ``insecure_demo``, ``source``, ``configured``.
    Never includes the value in raised error messages beyond presence.
    """
    if not secret_ref or not str(secret_ref).strip():
        return {
            "value": "",
            "insecure_demo": False,
            "source": None,
            "configured": False,
        }

    text = str(secret_ref).strip()
    lower = text.lower()

    if lower.startswith("insecure:") or lower.startswith("plaintext:"):
        prefix_len = text.index(":") + 1
        value = text[prefix_len:]
        return {
            "value": value,
            "insecure_demo": True,
            "source": "insecure_demo",
            "configured": bool(value),
        }

    if lower.startswith("env:"):
        name = text[4:].strip()
    elif _ENV_NAME_RE.match(text):
        name = text
    else:
        raise SecretRefError(
            "unrecognized secret_ref form (expected env: or insecure:/plaintext:)"
        )

    if not _ENV_NAME_RE.match(name):
        raise SecretRefError(
            f"secret_ref env name must match {_ENV_NAME_RE.pattern}"
        )
    value = os.getenv(name, "").strip()
    return {
        "value": value,
        "insecure_demo": False,
        "source": f"env:{name}",
        "configured": bool(value),
    }
