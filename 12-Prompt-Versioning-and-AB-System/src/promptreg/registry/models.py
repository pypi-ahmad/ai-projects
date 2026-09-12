"""Registry data types."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

Env = Literal["prod", "staging"]

_SLUG_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def _validate_slug(name: str) -> str:
    if not name or name[0] == "-" or name[-1] == "-" or "--" in name:
        msg = f"name must be a slug (lowercase, digits, single hyphens): {name!r}"
        raise ValueError(msg)
    if not set(name) <= _SLUG_CHARS:
        msg = f"name must be a slug (lowercase, digits, hyphens): {name!r}"
        raise ValueError(msg)
    return name


class Prompt(BaseModel):
    name: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name_is_slug(cls, v: str) -> str:
        return _validate_slug(v)


class PromptConfig(BaseModel):
    model: str
    provider: str
    temperature: float | None = None
    max_tokens: int | None = None


class Version(BaseModel):
    prompt_id: str
    version: int
    label: str | None = None
    sha256: str
    body_path: str
    config: PromptConfig
    created_at: datetime
    author: str
    changelog: str
    immutable: Literal[True] = True
    body: str | None = None
    """Populated by `get`; omitted (None) by `list_versions`, which never touches disk."""


class Pointer(BaseModel):
    prompt_id: str
    env: Env
    version: int
    updated_at: datetime
