"""Execution result types."""

from __future__ import annotations

from pydantic import BaseModel

from promptreg.registry.models import PromptConfig


class ExecutionResult(BaseModel):
    body: str
    config: PromptConfig
    dry: bool
    output: str | None = None
    ok: bool
    latency_ms: float
