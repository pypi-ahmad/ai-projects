"""Request/response bodies specific to the HTTP API.

Existing domain models (`Version`, `Pointer`, `Experiment`, `OutcomeEvent`,
...) are reused directly as responses — no need to redeclare them here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from promptreg.outcomes.models import OutcomeMetrics
from promptreg.registry.models import Env, PromptConfig
from promptreg.split.models import Arm


class PublishVersionRequest(BaseModel):
    body: str
    config: PromptConfig
    changelog: str
    author: str
    description: str | None = None
    label: str | None = None


class SetPointerRequest(BaseModel):
    version: int


class CreateExperimentRequest(BaseModel):
    name: str
    prompt_name: str
    arms: list[Arm]
    sticky_salt: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None


class ResolveRequest(BaseModel):
    prompt_name: str
    user_key: str
    env: Env


class ResolveResponse(BaseModel):
    version: int
    arm: str | None
    experiment_id: int | None
    reason: str
    body: str
    config: PromptConfig


class CompleteRequest(BaseModel):
    prompt_name: str
    user_key: str
    variables: dict[str, Any]
    env: Env


class CompleteResponse(BaseModel):
    request_id: str
    version: int
    arm: str | None
    experiment_id: int | None
    reason: str
    rendered: str
    dry: bool
    output: str | None
    ok: bool
    latency_ms: float


class TrackRequest(BaseModel):
    request_id: str
    metrics: OutcomeMetrics
