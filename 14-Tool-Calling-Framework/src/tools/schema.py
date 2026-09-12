"""ToolSpec: the typed contract a registered tool must satisfy.

Next: registry.py, which holds these by name and is what a tool actually
gets registered into.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

# Also the exact string a model must emit to call this tool -- kept
# simple and unambiguous against surrounding prompt/tool-result text.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class ToolArgs(BaseModel):
    """Base for every tool's args model: unknown fields are a validation
    error, not silently dropped -- a model hallucinating an extra argument
    should fail loudly, not have it ignored."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class ToolPermissions:
    """Sandbox permission flags for one tool. Default: CPU-only."""

    cpu: bool = True
    fs_read: bool = False
    fs_write: bool = False
    network: bool = False
    shell: bool = False


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A registered, typed, allowlisted tool."""

    name: str
    description: str
    permissions: ToolPermissions
    args_model: type[BaseModel]
    result_model: type[BaseModel]
    fn: Callable[..., Any]
    timeout_s: float
    max_retries: int

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            msg = f"invalid tool name: {self.name!r} (must match {_NAME_RE.pattern})"
            raise ValueError(msg)
