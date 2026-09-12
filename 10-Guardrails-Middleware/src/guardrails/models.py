"""Pydantic data model for the ordered-detector guard pipeline (Phase 2).

Defines the shapes `Pipeline.run()` (see `pipeline.py`) passes between
detectors and hands back to callers. Must not gain a field that can carry
raw matched text -- that's what makes `Finding`/`GuardDecision` safe to log
or return over the API (see `Span` below). Next: `pipeline.py` for how these
types actually flow through a run.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from guardrails.policies import (
    Policy,  # noqa: TC001 - pydantic needs this at runtime, not just for type checkers
)

Severity = Literal["info", "warn", "block"]
Action = Literal["allow", "transform", "block"]
Direction = Literal["input", "output"]
FailMode = Literal["closed", "open"]


class Span(BaseModel):
    """One matched region of text a detector flagged.

    Deliberately has no field for the raw matched text -- only offsets, a
    `type` label, a `score`, and an optional `replacement`. This is a
    security invariant, not an oversight: it's what guarantees findings and
    logs can never carry raw PII/secrets forward (see `pii.py`).
    """

    start: int
    end: int
    type: str
    score: float
    replacement: str | None = None


class Finding(BaseModel):
    """One detector's result for a single run."""

    detector_id: str
    severity: Severity
    spans: list[Span] = Field(default_factory=list)
    message: str


class GuardContext(BaseModel):
    """Per-call context passed to every detector."""

    direction: Direction
    tenant: str | None = None
    route: str | None = None
    fail_mode: FailMode = "closed"


class GuardDecision(BaseModel):
    """Final outcome of running a pipeline once."""

    action: Action
    findings: list[Finding] = Field(default_factory=list)
    text_in: str
    text_out: str
    policy: Policy
    latency_ms: float


def drop_overlapping_spans(spans: list[Span]) -> list[Span]:
    """Keep the first span (by list order, then position) covering any given range."""
    ordered = sorted(spans, key=lambda s: s.start)
    kept: list[Span] = []
    cursor = 0
    for span in ordered:
        if span.start < cursor:
            continue
        kept.append(span)
        cursor = span.end
    return kept


def apply_spans(text: str, spans: list[Span]) -> str:
    """Apply every span carrying a `replacement`, left to right, to `text`."""
    replacing = sorted((s for s in spans if s.replacement is not None), key=lambda s: s.start)
    if not replacing:
        return text

    out: list[str] = []
    cursor = 0
    for span in replacing:
        if span.start < cursor:
            continue  # overlapping replacement; first one already consumed this range
        if span.replacement is None:  # unreachable: `replacing` already filtered these out
            continue
        out.append(text[cursor : span.start])
        out.append(span.replacement)
        cursor = span.end
    out.append(text[cursor:])
    return "".join(out)
