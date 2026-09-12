"""Shared data types for the guardrails pipeline.

Phase 1 leftovers: this dataclass `Finding`/`Severity` is a distinct type
from -- and not interchangeable with -- the pydantic `Finding` in
`guardrails.models` that the live `Pipeline` actually uses. The only
consumer is `detectors.py`, which is itself unwired from the running app;
don't assume these types matter to `Guard`/`Pipeline` without checking there
first. Next: `detectors.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["low", "medium", "high"]
Detector = Literal["pii", "injection", "pipeline"]


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing a detector matched in a piece of text."""

    detector: Detector
    category: str
    severity: Severity
    span: tuple[int, int]
    matched_text: str  # raw text -- unlike guardrails.models.Span, which deliberately omits this


@dataclass(slots=True)
class Verdict:
    """Result of running a pipeline check over a piece of text."""

    allowed: bool
    text: str
    findings: list[Finding] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
