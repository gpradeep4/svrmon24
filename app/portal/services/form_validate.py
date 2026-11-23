"""Field-level validation for catalog form submissions."""

from __future__ import annotations

import re
from typing import Any

from ..models.catalog import FormSchema


class FormValidationError(Exception):
    def __init__(self, field_errors: dict[str, str]) -> None:
        super().__init__("form validation failed")
        self.field_errors = field_errors


_PATH_BAD = re.compile(r"(\.\.|[\x00])")
_USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)
_IP = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)$"
)


def validate_form_values(
    schema: FormSchema | dict[str, Any],
    values: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate and normalize form values against a catalog form schema."""
    if isinstance(schema, dict):
        schema = FormSchema.model_validate(schema)
    raw = values or {}
    if not isinstance(raw, dict):
        raise FormValidationError({"_form": "form_values must be an object"})

    known = {f.name for f in schema.fields}
    errors: dict[str, str] = {}
    for key in raw:
        if key not in known:
            errors[key] = "unknown field"
    if errors:
        raise FormValidationError(errors)

    out: dict[str, Any] = {}
    for field in schema.fields:
        present = field.name in raw
        value = raw.get(field.name, field.default)
        if value is None or value == "":
            if field.required:
                errors[field.name] = "required"
                continue
            if field.default is not None:
                out[field.name] = field.default
            continue
        try:
            out[field.name] = _coerce_field(field.type, value, field)
        except ValueError as exc:
            errors[field.name] = str(exc)

    if errors:
        raise FormValidationError(errors)
    return out


def _coerce_field(ftype: str, value: Any, field: Any) -> Any:
    if ftype == "boolean":
        if isinstance(value, bool):
            return value
        if str(value).lower() in {"1", "true", "yes"}:
            return True
        if str(value).lower() in {"0", "false", "no"}:
            return False
        raise ValueError("must be boolean")
    if ftype in {"integer", "number"}:
        try:
            num = int(value) if ftype == "integer" else float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"must be {ftype}") from exc
        if field.minimum is not None and num < field.minimum:
            raise ValueError(f"must be >= {field.minimum}")
        if field.maximum is not None and num > field.maximum:
            raise ValueError(f"must be <= {field.maximum}")
        return num
    if ftype == "enum":
        if field.multi:
            if not isinstance(value, list):
                raise ValueError("must be a list")
            bad = [v for v in value if str(v) not in field.options]
            if bad:
                raise ValueError("invalid option")
            return [str(v) for v in value]
        if str(value) not in field.options:
            raise ValueError("invalid option")
        return str(value)
    text = str(value)
    if field.min_length is not None and len(text) < field.min_length:
        raise ValueError(f"min length {field.min_length}")
    if field.max_length is not None and len(text) > field.max_length:
        raise ValueError(f"max length {field.max_length}")
    if field.pattern:
        if not re.search(field.pattern, text):
            raise ValueError("pattern mismatch")
    if ftype == "path":
        if _PATH_BAD.search(text) or text.startswith("-"):
            raise ValueError("invalid path")
    if ftype == "username" and not _USERNAME.match(text):
        raise ValueError("invalid username")
    if ftype == "hostname" and not _HOSTNAME.match(text):
        raise ValueError("invalid hostname")
    if ftype == "ip" and not _IP.match(text):
        raise ValueError("invalid ip")
    if ftype == "secret_ref":
        if "/" in text or " " in text or not text:
            raise ValueError("secret_ref must be an env/secret name")
    return text
