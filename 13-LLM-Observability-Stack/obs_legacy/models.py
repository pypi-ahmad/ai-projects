"""Shared record types for traces and alerts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime


def new_trace_id() -> str:
    return uuid.uuid4().hex


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TraceRecord:
    trace_id: str
    ts: str
    provider: str
    model: str
    prompt_hash: str | None
    prompt_preview: str | None
    response_hash: str | None
    response_preview: str | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: float | None
    cost_usd: float | None
    priced: bool
    status: str
    error: str | None = None


@dataclass
class Alert:
    trace_id: str
    ts: str
    rule: str
    severity: str
    message: str
    llm_note: str | None = None
