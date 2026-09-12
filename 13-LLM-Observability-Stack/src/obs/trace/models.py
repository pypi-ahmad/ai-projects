"""Trace/Span/Usage schema.

Pure data models only - no I/O, no exporter/pricing logic. `tracer.py`
constructs and mutates these; `export/` reads and writes them to
SQLite/JSONL; `metrics/pricing.py` fills in `Usage.cost_est` at export
time, not here. See docs/SCHEMA.md for the field reference and
docs/PRIVACY.md for what belongs in `attrs` vs. a real field. Next file to
read: tracer.py (how these get instantiated and mutated).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SpanContext(BaseModel):
    trace_id: str
    span_id: str
    parent_id: str | None = None  # None marks the trace's root span


class Usage(BaseModel):
    in_tokens: int | None = None
    out_tokens: int | None = None
    cost_est: float | None = None
    ttft_ms: float | None = None


class Span(BaseModel):
    ctx: SpanContext
    name: str
    kind: Literal["client", "internal"] = "internal"
    provider: str | None = None
    model: str | None = None
    ts: str  # wall-clock ISO 8601 UTC; start_ns is monotonic, not calendar time
    start_ns: int
    end_ns: int | None = None
    latency_ms: float | None = None
    status: Literal["ok", "error"] = "ok"
    error: str | None = None
    usage: Usage | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)


class Trace(BaseModel):
    trace_id: str
    spans: list[Span] = Field(default_factory=list)
    # free-form; recognized keys include tenant, route, prompt_name, prompt_version
    attrs: dict[str, Any] = Field(default_factory=dict)
