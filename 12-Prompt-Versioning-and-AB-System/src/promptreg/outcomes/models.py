"""Outcome event types."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Thumbs = Literal[1, -1]


class OutcomeMetrics(BaseModel):
    thumbs: Thumbs | None = None
    task_ok: bool | None = None
    tokens_out: int | None = None
    custom: dict = Field(default_factory=dict)


class OutcomeEvent(BaseModel):
    request_id: str
    ts: datetime
    user_key_hash: str
    prompt_name: str
    version: int
    arm: str | None
    experiment_id: int | None
    latency_ms: float
    ok: bool
    metrics: OutcomeMetrics
