"""Request/response models for endpoints not already covered by obs.trace/obs.alerts models."""

from __future__ import annotations

from pydantic import BaseModel


class Message(BaseModel):
    role: str
    content: str


class CompleteRequest(BaseModel):
    messages: list[Message]
    provider: str
    model: str


class CompleteResponse(BaseModel):
    text: str
    trace_id: str
    in_tokens: int | None
    out_tokens: int | None
    ttft_ms: float | None


class IngestResponse(BaseModel):
    trace_id: str
    spans: int
