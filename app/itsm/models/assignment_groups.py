"""Assignment group directory models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clean_id_list(values: list[str] | None, *, limit: int = 200) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item[:128])
        if len(out) >= limit:
            break
    return out


class AssignmentGroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    email: str | None = Field(default=None, max_length=320)
    member_user_ids: list[str] = Field(default_factory=list, max_length=200)
    active: bool = True

    @field_validator("name", "description", "email", mode="before")
    @classmethod
    def _strip_opt(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("member_user_ids", mode="before")
    @classmethod
    def _members(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("member_user_ids must be a list")
        return _clean_id_list([str(v) for v in value])


class AssignmentGroupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    email: str | None = Field(default=None, max_length=320)
    member_user_ids: list[str] | None = Field(default=None, max_length=200)
    active: bool | None = None

    @field_validator("name", "description", "email", mode="before")
    @classmethod
    def _strip_opt(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("member_user_ids", mode="before")
    @classmethod
    def _members(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("member_user_ids must be a list")
        return _clean_id_list([str(v) for v in value])
